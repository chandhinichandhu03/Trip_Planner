import os
import sys
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_file
from sqlalchemy import text
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

# Ensure the app.py folder is in python sys.path for absolute imports
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from ai_engine import ai_engine, UPLOAD_DIR
from exporter import generate_itinerary_pdf, generate_expenses_csv

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATE_DIR = os.path.join(BASE_DIR, 'templates')
STATIC_DIR = os.path.join(BASE_DIR, 'static')

app = Flask(__name__, template_folder=TEMPLATE_DIR, static_folder=STATIC_DIR)
app.config['SECRET_KEY'] = 'globetrotter_secret_key_123'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(BASE_DIR, 'instance', 'globetrotter.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# --- Gamification / XP Helper ---
def add_xp(user, amount, reason=""):
    """Award XP to the user, handle levels, and trigger local notification alerts"""
    if not user or not user.is_authenticated:
        return
    user.xp = (user.xp or 0) + amount
    user.points = (user.points or 0) + amount
    
    # Simple Level Threshold calculation: Level = sqrt(XP / 100) + 1
    new_level = int((user.xp / 100) ** 0.5) + 1
    leveled_up = False
    if new_level > (user.level or 1):
        user.level = new_level
        leveled_up = True
        
    db.session.commit()
    
    # Create notification log
    title = f"Earned +{amount} XP!"
    content = f"Awarded for: {reason}"
    if leveled_up:
        title = f"Leveled Up to Level {new_level}! 🎉"
        content = f"Congratulations! You've reached Level {new_level}. Keep exploring the globe!"
        
    notif = Notification(user_id=user.id, title=title, content=content, type="achievement")
    db.session.add(notif)
    db.session.commit()

# --- Database Models ---

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(150), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    
    # Gamification
    xp = db.Column(db.Integer, default=0)
    level = db.Column(db.Integer, default=1)
    points = db.Column(db.Integer, default=0)
    
    trips = db.relationship('Trip', backref='author', lazy=True, cascade="all, delete-orphan")
    achievements = db.relationship('UserAchievement', backref='user', lazy=True, cascade="all, delete-orphan")
    notifications = db.relationship('Notification', backref='user', lazy=True, cascade="all, delete-orphan")
    chat_messages = db.relationship('ChatMessage', backref='user', lazy=True, cascade="all, delete-orphan")
    documents = db.relationship('UploadedDocument', backref='user', lazy=True, cascade="all, delete-orphan")
    journal_entries = db.relationship('JournalEntry', backref='user', lazy=True, cascade="all, delete-orphan")

class UserAchievement(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    achievement_key = db.Column(db.String(100), nullable=False)
    title = db.Column(db.String(150), nullable=False)
    unlocked_at = db.Column(db.DateTime, default=datetime.utcnow)

class Trip(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    destination = db.Column(db.String(100), nullable=False)
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    is_public = db.Column(db.Boolean, default=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    estimated_budget = db.Column(db.Float, nullable=True, default=0.0)
    style = db.Column(db.String(50), default="Solo") # Solo, Family, Honeymoon, Adventure, Luxury, Backpacking
    
    sections = db.relationship('TripSection', backref='trip', lazy=True, cascade="all, delete-orphan")
    stops = db.relationship('Stop', backref='trip', lazy=True, cascade="all, delete-orphan")
    expenses = db.relationship('Expense', backref='trip', lazy=True, cascade="all, delete-orphan")
    journal_entries = db.relationship('JournalEntry', backref='trip', lazy=True, cascade="all, delete-orphan")
    packing_lists = db.relationship('PackingList', backref='trip', lazy=True, cascade="all, delete-orphan")
    places = db.relationship('PlaceOfInterest', backref='trip', lazy=True, cascade="all, delete-orphan")
    
    # Social Interactions
    likes = db.relationship('Like', backref='trip', lazy=True, cascade="all, delete-orphan")
    bookmarks = db.relationship('Bookmark', backref='trip', lazy=True, cascade="all, delete-orphan")
    comments = db.relationship('Comment', backref='trip', lazy=True, cascade="all, delete-orphan")
    ratings = db.relationship('Rating', backref='trip', lazy=True, cascade="all, delete-orphan")

class TripSection(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    trip_id = db.Column(db.Integer, db.ForeignKey('trip.id'), nullable=False)
    title = db.Column(db.String(100), nullable=False)
    activity = db.Column(db.Text, nullable=False)
    budget = db.Column(db.Float, default=0.0)
    date = db.Column(db.Date, nullable=True)

class City(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    country = db.Column(db.String(150), nullable=True)
    cost_index = db.Column(db.Float, default=1.0)
    popularity = db.Column(db.Integer, default=0)

class Stop(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    trip_id = db.Column(db.Integer, db.ForeignKey('trip.id'), nullable=False)
    city_id = db.Column(db.Integer, db.ForeignKey('city.id'), nullable=False)
    arrival = db.Column(db.Date, nullable=True)
    depart = db.Column(db.Date, nullable=True)
    ord = db.Column(db.Integer, default=0)
    city = db.relationship('City')
    activities = db.relationship('Activity', backref='stop', lazy=True, cascade="all, delete-orphan")

class Activity(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    stop_id = db.Column(db.Integer, db.ForeignKey('stop.id'), nullable=False)
    title = db.Column(db.String(150), nullable=False)
    description = db.Column(db.Text, nullable=True)
    cost = db.Column(db.Float, default=0.0)
    duration_hours = db.Column(db.Float, default=1.0)
    category = db.Column(db.String(100), nullable=True)

# --- NEW Models for Advanced Features ---

class Expense(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    trip_id = db.Column(db.Integer, db.ForeignKey('trip.id'), nullable=False)
    title = db.Column(db.String(150), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    category = db.Column(db.String(100), nullable=False, default="Others") # Transport, Lodging, Food, Activities, Shopping, Others
    date = db.Column(db.Date, nullable=True)
    description = db.Column(db.Text, nullable=True)

class JournalEntry(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    trip_id = db.Column(db.Integer, db.ForeignKey('trip.id'), nullable=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    content = db.Column(db.Text, nullable=False)
    date = db.Column(db.Date, default=datetime.utcnow().date)
    photo_path = db.Column(db.String(250), nullable=True)
    is_favorite = db.Column(db.Boolean, default=False)
    tags = db.Column(db.String(200), nullable=True) # comma separated tags

class PackingList(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    trip_id = db.Column(db.Integer, db.ForeignKey('trip.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    name = db.Column(db.String(150), nullable=False)
    category = db.Column(db.String(100), nullable=False, default="General") # Clothing, Electronics, Medicine, Essentials
    items = db.relationship('PackingItem', backref='packing_list', lazy=True, cascade="all, delete-orphan")

class PackingItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    packing_list_id = db.Column(db.Integer, db.ForeignKey('packing_list.id'), nullable=False)
    name = db.Column(db.String(200), nullable=False)
    is_completed = db.Column(db.Boolean, default=False)
    quantity = db.Column(db.Integer, default=1)

class PlaceOfInterest(db.Model):
    """Offline maps location database logs"""
    id = db.Column(db.Integer, primary_key=True)
    trip_id = db.Column(db.Integer, db.ForeignKey('trip.id'), nullable=False)
    name = db.Column(db.String(200), nullable=False)
    lat = db.Column(db.Float, nullable=True)
    lng = db.Column(db.Float, nullable=True)
    category = db.Column(db.String(100), default="Sightseeing") # Dining, Sightseeing, Lodging, Transit
    notes = db.Column(db.Text, nullable=True)
    contact = db.Column(db.String(150), nullable=True)

class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    content = db.Column(db.Text, nullable=False)
    type = db.Column(db.String(50), default="info") # info, budget, achievement, social
    is_read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class ChatMessage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    role = db.Column(db.String(50), nullable=False) # user, assistant
    content = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

class UploadedDocument(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    filename = db.Column(db.String(200), nullable=False)
    filepath = db.Column(db.String(250), nullable=False)
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)

class SearchHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    query = db.Column(db.String(200), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

# --- Social Interaction Tables ---
class Like(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    trip_id = db.Column(db.Integer, db.ForeignKey('trip.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Bookmark(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    trip_id = db.Column(db.Integer, db.ForeignKey('trip.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Comment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    trip_id = db.Column(db.Integer, db.ForeignKey('trip.id'), nullable=False)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user = db.relationship('User', backref='comments')

class Rating(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    trip_id = db.Column(db.Integer, db.ForeignKey('trip.id'), nullable=False)
    rating = db.Column(db.Integer, nullable=False) # 1 to 5
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Follow(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    follower_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    followed_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    follower = db.relationship('User', foreign_keys=[follower_id], backref=db.backref('following', lazy='dynamic'))
    followed = db.relationship('User', foreign_keys=[followed_id], backref=db.backref('followers', lazy='dynamic'))


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# --- Achievement Checker Helper ---
def check_and_unlock_achievement(user, key, title):
    """Utility to unlock achievements and award bonus XP"""
    exists = UserAchievement.query.filter_by(user_id=user.id, achievement_key=key).first()
    if not exists:
        ach = UserAchievement(user_id=user.id, achievement_key=key, title=title)
        db.session.add(ach)
        db.session.commit()
        add_xp(user, 100, f"Unlocked Achievement: {title}! 🏆")

# --- Routes & Views ---

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        user = User.query.filter_by(email=email).first()
        if user and check_password_hash(user.password, password):
            login_user(user)
            # Add micro XP for logging in
            add_xp(user, 5, "Daily login check-in")
            return redirect(url_for('dashboard'))
        flash('Invalid credentials')
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        email = request.form.get('email')
        username = request.form.get('username')
        password = request.form.get('password')
        if User.query.filter_by(email=email).first():
            flash('Email already exists')
            return redirect(url_for('register'))
        hashed_pw = generate_password_hash(password, method='pbkdf2:sha256')
        new_user = User(email=email, username=username, password=hashed_pw, xp=0, level=1, points=0)
        if User.query.count() == 0: new_user.is_admin = True
        db.session.add(new_user)
        db.session.commit()
        login_user(new_user)
        add_xp(new_user, 50, "Welcome to GlobeTrotter! Account created.")
        return redirect(url_for('dashboard'))
    return render_template('register.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/')
@login_required
def dashboard():
    user_trips = Trip.query.filter_by(user_id=current_user.id).order_by(Trip.start_date.desc()).all()
    
    # Calculate global dashboard metrics
    total_trips = len(user_trips)
    completed_trips = 0
    upcoming_trips = 0
    total_spent = 0.0
    
    today = datetime.utcnow().date()
    for t in user_trips:
        if t.end_date < today:
            completed_trips += 1
        else:
            upcoming_trips += 1
        
        # calculate cost
        section_cost = sum((s.budget or 0) for s in t.sections)
        activity_cost = sum((a.cost or 0) for s in t.stops for a in s.activities)
        expense_cost = sum((e.amount or 0) for e in t.expenses)
        total_spent += section_cost + activity_cost + expense_cost

    # Local Recommendation Engine (collaborative-filtering / destination popularity mock)
    # Recommend public trips other than user's own, sorting by popularity (likes)
    recommended_trips = Trip.query.filter(Trip.is_public == True, Trip.user_id != current_user.id).all()
    # Sort recommendations by likes count
    recommended_trips = sorted(recommended_trips, key=lambda x: len(x.likes), reverse=True)[:4]

    # Fetch recent unread notifications
    notifs = Notification.query.filter_by(user_id=current_user.id, is_read=False).order_by(Notification.created_at.desc()).limit(5).all()

    return render_template('dashboard.html', trips=user_trips[:3], all_trips=user_trips,
                           total_trips=total_trips, completed_trips=completed_trips,
                           upcoming_trips=upcoming_trips, total_spent=total_spent,
                           recommended_trips=recommended_trips, notifications=notifs)

@app.route('/create_trip', methods=['GET', 'POST'])
@login_required
def create_trip():
    if request.method == 'POST':
        name = request.form.get('name')
        dest = request.form.get('destination')
        start = datetime.strptime(request.form.get('start_date'), '%Y-%m-%d').date()
        end = datetime.strptime(request.form.get('end_date'), '%Y-%m-%d').date()
        is_public = True if request.form.get('is_public') else False
        estimated_budget = float(request.form.get('estimated_budget') or 0)
        style = request.form.get('style', 'Solo')
        
        new_trip = Trip(name=name, destination=dest, start_date=start, end_date=end, 
                        is_public=is_public, estimated_budget=estimated_budget, 
                        style=style, author=current_user)
        db.session.add(new_trip)
        db.session.commit()
        
        add_xp(current_user, 100, f"Created a new trip to {dest}")
        check_and_unlock_achievement(current_user, "first_trip", "Maiden Voyage")
        
        return redirect(url_for('view_trip', trip_id=new_trip.id))
    return render_template('create_trip.html')

@app.route('/trip/<int:trip_id>/delete', methods=['POST'])
@login_required
def delete_trip(trip_id):
    trip = Trip.query.get_or_404(trip_id)
    if trip.user_id != current_user.id:
        flash("Unauthorized deletion attempt.")
        return redirect(url_for('dashboard'))
    
    db.session.delete(trip)
    db.session.commit()
    flash("Trip plan deleted successfully.")
    return redirect(url_for('dashboard'))

@app.route('/trip/<int:trip_id>')
def view_trip(trip_id):
    trip = Trip.query.get_or_404(trip_id)
    if not trip.is_public and (not current_user.is_authenticated or trip.user_id != current_user.id):
        flash("You do not have permission to view this trip.")
        return redirect(url_for('dashboard'))
        
    # calculate costs
    section_cost = sum((s.budget or 0) for s in trip.sections)
    activity_cost = sum((a.cost or 0) for stop in trip.stops for a in stop.activities)
    expense_cost = sum((e.amount or 0) for e in trip.expenses)
    total_cost = section_cost + activity_cost + expense_cost
    
    # budget health status
    budget_status = None
    health_score = 100
    if trip.estimated_budget and trip.estimated_budget > 0:
        diff = trip.estimated_budget - total_cost
        if diff < 0:
            budget_status = {'status': 'over', 'amount': abs(diff)}
            health_score = max(0, int(100 - (abs(diff) / trip.estimated_budget * 100)))
        else:
            budget_status = {'status': 'under', 'amount': diff}
            health_score = int((diff / trip.estimated_budget) * 100)
            
    # Category statistics for Chart.js
    category_summary = {}
    for stop in trip.stops:
        for act in stop.activities:
            cat = act.category or "Activities"
            category_summary[cat] = category_summary.get(cat, 0.0) + (act.cost or 0.0)
    for exp in trip.expenses:
        cat = exp.category or "Others"
        category_summary[cat] = category_summary.get(cat, 0.0) + (exp.amount or 0.0)
    for sec in trip.sections:
        category_summary["Sections"] = category_summary.get("Sections", 0.0) + (sec.budget or 0.0)

    # Sort stops chronologically
    sorted_stops = sorted(trip.stops, key=lambda x: x.ord or 0)

    # Comments and ratings
    comments = Comment.query.filter_by(trip_id=trip.id).order_by(Comment.created_at.desc()).all()
    ratings = Rating.query.filter_by(trip_id=trip.id).all()
    avg_rating = sum(r.rating for r in ratings) / len(ratings) if ratings else 0.0

    user_liked = False
    user_bookmarked = False
    if current_user.is_authenticated:
        user_liked = Like.query.filter_by(user_id=current_user.id, trip_id=trip.id).first() is not None
        user_bookmarked = Bookmark.query.filter_by(user_id=current_user.id, trip_id=trip.id).first() is not None

    return render_template('trip_view.html', trip=trip, total_cost=total_cost, 
                           budget_status=budget_status, health_score=health_score,
                           section_cost=section_cost, activity_cost=activity_cost, 
                           expense_cost=expense_cost, category_summary=category_summary,
                           stops=sorted_stops, comments=comments, avg_rating=avg_rating,
                           ratings_count=len(ratings), user_liked=user_liked, 
                           user_bookmarked=user_bookmarked)

@app.route('/public/trip/<int:trip_id>')
def public_trip(trip_id):
    # Public views are handles natively in view_trip with read_only toggle
    trip = Trip.query.get_or_404(trip_id)
    if not trip.is_public:
        flash('This trip is not public.')
        return redirect(url_for('dashboard'))
    return redirect(url_for('view_trip', trip_id=trip_id))

# --- Section Actions ---
@app.route('/trip/<int:trip_id>/add_section', methods=['POST'])
@login_required
def add_section(trip_id):
    trip = Trip.query.get_or_404(trip_id)
    if trip.user_id != current_user.id: return "Unauthorized", 403
    title = request.form.get('title')
    activity = request.form.get('activity')
    budget = float(request.form.get('budget') or 0)
    date_str = request.form.get('date')
    date = datetime.strptime(date_str, '%Y-%m-%d').date() if date_str else None
    
    new_section = TripSection(trip_id=trip.id, title=title, activity=activity, budget=budget, date=date)
    db.session.add(new_section)
    db.session.commit()
    
    add_xp(current_user, 10, "Added trip section itinerary")
    return redirect(url_for('view_trip', trip_id=trip.id))

@app.route('/delete_section/<int:section_id>')
@login_required
def delete_section(section_id):
    section = TripSection.query.get_or_404(section_id)
    if section.trip.user_id != current_user.id: return "Unauthorized", 403
    trip_id = section.trip.id
    db.session.delete(section)
    db.session.commit()
    return redirect(url_for('view_trip', trip_id=trip_id))

# --- Stop Actions ---
@app.route('/trip/<int:trip_id>/add_stop', methods=['POST'])
@login_required
def add_stop(trip_id):
    trip = Trip.query.get_or_404(trip_id)
    if trip.user_id != current_user.id: return "Unauthorized", 403
    city_name = request.form.get('city')
    arrival = request.form.get('arrival')
    depart = request.form.get('depart')
    
    city = City.query.filter_by(name=city_name).first()
    if not city:
        city = City(name=city_name, popularity=1)
        db.session.add(city)
    else:
        city.popularity = (city.popularity or 0) + 1
        
    db.session.commit()
    
    new_stop = Stop(trip_id=trip.id, city_id=city.id,
                    arrival=(datetime.strptime(arrival, '%Y-%m-%d').date() if arrival else None),
                    depart=(datetime.strptime(depart, '%Y-%m-%d').date() if depart else None),
                    ord=(Stop.query.filter_by(trip_id=trip.id).count() + 1))
    db.session.add(new_stop)
    db.session.commit()
    
    add_xp(current_user, 10, f"Added destination stop {city_name}")
    # Unlock Explorer achievement if stops count >= 5
    stops_count = Stop.query.join(Trip).filter(Trip.user_id == current_user.id).count()
    if stops_count >= 5:
        check_and_unlock_achievement(current_user, "explorer", "Master Explorer")
        
    return redirect(url_for('view_trip', trip_id=trip.id))

@app.route('/trip/<int:trip_id>/add_activity', methods=['POST'])
@login_required
def add_activity(trip_id):
    trip = Trip.query.get_or_404(trip_id)
    if trip.user_id != current_user.id: return "Unauthorized", 403
    stop_id = request.form.get('stop_id')
    title = request.form.get('title')
    description = request.form.get('description')
    cost = float(request.form.get('cost') or 0)
    duration = float(request.form.get('duration') or 1)
    category = request.form.get('category', 'Sightseeing')
    
    stop = Stop.query.get_or_404(int(stop_id))
    new_act = Activity(stop_id=stop.id, title=title, description=description, cost=cost, duration_hours=duration, category=category)
    db.session.add(new_act)
    db.session.commit()
    
    add_xp(current_user, 10, f"Planned activity: {title}")
    return redirect(url_for('view_trip', trip_id=trip.id))

# --- API/Drag-drop Reordering Stops ---
@app.route('/api/trip/<int:trip_id>/reorder_stops', methods=['POST'])
@login_required
def api_reorder_stops(trip_id):
    trip = Trip.query.get_or_404(trip_id)
    if trip.user_id != current_user.id: return jsonify({'error': 'unauthorized'}), 403
    
    order_data = request.json.get('orders', []) # list of Stop IDs in order
    for idx, stop_id in enumerate(order_data):
        stop = Stop.query.filter_by(id=stop_id, trip_id=trip.id).first()
        if stop:
            stop.ord = idx + 1
            
    db.session.commit()
    return jsonify({'success': True})

# --- Expenses APIs ---
@app.route('/trip/<int:trip_id>/add_expense', methods=['POST'])
@login_required
def add_expense(trip_id):
    trip = Trip.query.get_or_404(trip_id)
    if trip.user_id != current_user.id: return "Unauthorized", 403
    
    title = request.form.get('title')
    amount = float(request.form.get('amount') or 0)
    category = request.form.get('category', 'Others')
    date_str = request.form.get('date')
    date = datetime.strptime(date_str, '%Y-%m-%d').date() if date_str else None
    description = request.form.get('description')
    
    new_expense = Expense(trip_id=trip.id, title=title, amount=amount, category=category, date=date, description=description)
    db.session.add(new_expense)
    db.session.commit()
    
    add_xp(current_user, 10, f"Logged expense of ${amount} for {title}")
    
    # AI trigger checks: Check if total spent is over budget, notify
    total_spent = sum(e.amount for e in trip.expenses) + sum(s.budget for s in trip.sections) + sum(a.cost for s in trip.stops for a in s.activities)
    if trip.estimated_budget and total_spent > trip.estimated_budget:
        notif = Notification(user_id=current_user.id, title=f"Budget Overrun Warning! ⚠️", 
                             content=f"Your planned costs for '{trip.name}' have hit ${total_spent:.2f}, exceeding your budget of ${trip.estimated_budget:.2f}.", 
                             type="budget")
        db.session.add(notif)
        db.session.commit()

    return redirect(url_for('view_trip', trip_id=trip.id))

@app.route('/trip/<int:trip_id>/delete_expense/<int:expense_id>')
@login_required
def delete_expense(trip_id, expense_id):
    trip = Trip.query.get_or_404(trip_id)
    if trip.user_id != current_user.id: return "Unauthorized", 403
    exp = Expense.query.get_or_404(expense_id)
    db.session.delete(exp)
    db.session.commit()
    return redirect(url_for('view_trip', trip_id=trip.id))

@app.route('/api/trip/<int:trip_id>/expenses/analysis')
@login_required
def api_expense_analysis(trip_id):
    trip = Trip.query.get_or_404(trip_id)
    if trip.user_id != current_user.id: return jsonify({'error': 'unauthorized'}), 403
    
    # Serialize expenses
    expenses = []
    for exp in trip.expenses:
        expenses.append({'amount': exp.amount, 'category': exp.category})
    for stop in trip.stops:
        for act in stop.activities:
            expenses.append({'amount': act.cost, 'category': act.category or "Activities"})
    for sec in trip.sections:
        expenses.append({'amount': sec.budget, 'category': 'General Plan'})
        
    analysis = ai_engine.analyze_expenses_and_suggest(expenses, trip.estimated_budget or 0.0)
    check_and_unlock_achievement(current_user, "budget_expert", "Budget Warden")
    return jsonify({'analysis': analysis})

# --- RAG Travel Chat ---
@app.route('/ai_chat')
@login_required
def ai_chat_view():
    chat_history = ChatMessage.query.filter_by(user_id=current_user.id).order_by(ChatMessage.timestamp.asc()).all()
    docs = UploadedDocument.query.filter_by(user_id=current_user.id).all()
    return render_template('ai_chat.html', chat_history=chat_history, documents=docs)

@app.route('/api/ai/chat', methods=['POST'])
@login_required
def api_ai_chat():
    user_msg = request.json.get('message', '').strip()
    if not user_msg:
        return jsonify({'error': 'Empty message'}), 400
    
    # Save user message
    msg_user = ChatMessage(user_id=current_user.id, role='user', content=user_msg)
    db.session.add(msg_user)
    db.session.commit()
    
    # Get recent conversation history
    history = []
    past_messages = ChatMessage.query.filter_by(user_id=current_user.id).order_by(ChatMessage.timestamp.asc()).all()
    for msg in past_messages[-10:]:
        history.append({'role': msg.role, 'content': msg.content})
        
    # Search RAG guides
    context_docs = ai_engine.similarity_search(user_msg, user_id=current_user.id, k=3)
    
    # Query model
    ai_resp = ai_engine.travel_chat(user_msg, history, context_docs)
    
    # Save AI message
    msg_ai = ChatMessage(user_id=current_user.id, role='assistant', content=ai_resp)
    db.session.add(msg_ai)
    db.session.commit()
    
    return jsonify({'response': ai_resp})

@app.route('/api/ai/upload_rag', methods=['POST'])
@login_required
def api_ai_upload_rag():
    if 'file' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No file name'}), 400
        
    filename = secure_filename(file.filename)
    filepath = os.path.join(UPLOAD_DIR, filename)
    file.save(filepath)
    
    # Add to SQLite
    doc = UploadedDocument(user_id=current_user.id, filename=filename, filepath=filepath)
    db.session.add(doc)
    db.session.commit()
    
    # Chroma DB Ingest
    success, msg = ai_engine.ingest_document(filepath, user_id=current_user.id)
    if success:
        add_xp(current_user, 30, f"Uploaded custom travel guide: {filename}")
        check_and_unlock_achievement(current_user, "rag_wizard", "RAG Cartographer")
        return jsonify({'success': True, 'message': msg})
    else:
        return jsonify({'success': False, 'error': msg}), 500

@app.route('/api/ai/suggest_itinerary', methods=['POST'])
@login_required
def api_ai_suggest_itinerary():
    destination = request.json.get('destination')
    duration = int(request.json.get('duration', 3))
    budget = float(request.json.get('budget', 500))
    style = request.json.get('style', 'Solo')
    
    itinerary_text = ai_engine.generate_day_wise_itinerary(destination, duration, budget, style)
    return jsonify({'itinerary': itinerary_text})

# --- AI Packing Checklist ---
@app.route('/trip/<int:trip_id>/packing')
@login_required
def trip_packing_view(trip_id):
    trip = Trip.query.get_or_404(trip_id)
    if trip.user_id != current_user.id: return "Unauthorized", 403
    return render_template('packing.html', trip=trip)

@app.route('/api/trip/<int:trip_id>/packing/generate', methods=['POST'])
@login_required
def api_packing_generate(trip_id):
    trip = Trip.query.get_or_404(trip_id)
    if trip.user_id != current_user.id: return jsonify({'error': 'unauthorized'}), 403
    
    days = (trip.end_date - trip.start_date).days + 1
    ai_raw = ai_engine.generate_packing_list(trip.destination, days, trip.style or "Solo")
    
    import json
    
    # Clean the raw AI string of any markdown blocks (e.g., ```json or ```)
    raw_clean = ai_raw.strip()
    if raw_clean.startswith("```"):
        lines = raw_clean.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        raw_clean = "\n".join(lines).strip()

    categories = {}
    
    # Try parsing as JSON first
    try:
        data = json.loads(raw_clean)
        if isinstance(data, dict):
            for cat, val in data.items():
                cat_clean = str(cat).strip().replace('"', '').replace("'", "")
                if isinstance(val, list):
                    categories[cat_clean] = [str(item).strip().replace('"', '').replace("'", "") for item in val if item]
                elif isinstance(val, str):
                    categories[cat_clean] = [i.strip().replace('"', '').replace("'", "") for i in val.split(",") if i.strip()]
    except Exception:
        pass

    if not categories:
        # Fallback to line-by-line parsing
        current_cat = "Essentials"
        for line in ai_raw.split("\n"):
            line = line.strip()
            if not line:
                continue
            
            # Ignore decorative JSON brackets/braces
            if line in ["{", "}", "[", "]", "],", "]:"]:
                continue
                
            if (line.endswith(":") or ":" in line) and not line.startswith("http"):
                parts = line.split(":", 1)
                cat_name = parts[0].strip().replace("1.", "").replace("2.", "").replace("3.", "").replace("4.", "").replace("#", "").replace('"', '').replace("'", "").strip()
                if cat_name in ["{", "}", "[", "]"]:
                    continue
                current_cat = cat_name
                inline_items = parts[1].strip().strip("[]{}").replace('"', '').replace("'", "")
                if inline_items:
                    items = [i.strip() for i in inline_items.split(",") if i.strip()]
                    if items:
                        categories[current_cat] = items
            else:
                item_clean = line.lstrip("-*1234567890. ").strip().strip('",[]{}').strip("'").strip()
                if item_clean and item_clean not in ["[", "]", "{", "}"]:
                    categories.setdefault(current_cat, []).append(item_clean)
                
    # If parsing is empty, use standard fallbacks
    if not categories:
        categories = {
            "Clothing": ["Comfortable shoes", "Layered jacket", "Weather-appropriate tops", "Socks & Underwear"],
            "Electronics": ["Phone charger", "Power bank", "Universal Adapter"],
            "Medicine": ["First Aid kit", "Pain relievers", "Hand sanitizer"],
            "Essentials": ["Passport", "Tickets", "Credit card / Local cash"]
        }
        
    # Populate DB tables
    # Clean previous checklists
    PackingList.query.filter_by(trip_id=trip.id).delete()
    db.session.commit()
    
    for cat_title, items in categories.items():
        plist = PackingList(trip_id=trip.id, user_id=current_user.id, name=cat_title, category=cat_title)
        db.session.add(plist)
        db.session.flush()
        for item_name in items:
            pitem = PackingItem(packing_list_id=plist.id, name=item_name)
            db.session.add(pitem)
            
    db.session.commit()
    add_xp(current_user, 20, "AI checklist generated")
    
    return jsonify({'success': True})

@app.route('/api/packing/item/<int:item_id>/toggle', methods=['POST'])
@login_required
def api_packing_toggle(item_id):
    item = PackingItem.query.get_or_404(item_id)
    if item.packing_list.user_id != current_user.id: return jsonify({'error': 'unauthorized'}), 403
    item.is_completed = not item.is_completed
    db.session.commit()
    
    if item.is_completed:
        add_xp(current_user, 2, "Packed item checklist")
        
    return jsonify({'success': True, 'is_completed': item.is_completed})

@app.route('/api/packing/item/add', methods=['POST'])
@login_required
def api_packing_add():
    list_id = request.form.get('list_id')
    name = request.form.get('name')
    plist = PackingList.query.get_or_404(int(list_id))
    if plist.user_id != current_user.id: return "Unauthorized", 403
    
    item = PackingItem(packing_list_id=plist.id, name=name)
    db.session.add(item)
    db.session.commit()
    return redirect(url_for('trip_packing_view', trip_id=plist.trip_id))

# --- Travel Journal ---
@app.route('/trip/<int:trip_id>/journal')
@login_required
def trip_journal_view(trip_id):
    trip = Trip.query.get_or_404(trip_id)
    if trip.user_id != current_user.id: return "Unauthorized", 403
    entries = JournalEntry.query.filter_by(trip_id=trip.id, user_id=current_user.id).order_by(JournalEntry.date.desc()).all()
    return render_template('journal.html', trip=trip, entries=entries)

@app.route('/trip/<int:trip_id>/journal/add', methods=['POST'])
@login_required
def trip_journal_add(trip_id):
    trip = Trip.query.get_or_404(trip_id)
    if trip.user_id != current_user.id: return "Unauthorized", 403
    
    title = request.form.get('title')
    content = request.form.get('content')
    date_str = request.form.get('date')
    date = datetime.strptime(date_str, '%Y-%m-%d').date() if date_str else datetime.utcnow().date()
    tags = request.form.get('tags')
    is_fav = True if request.form.get('is_favorite') else False
    
    # Image uploads
    photo_path = None
    if 'photo' in request.files:
        photo = request.files['photo']
        if photo.filename != '':
            fname = secure_filename(photo.filename)
            photo_dir = os.path.join(STATIC_DIR, 'uploads', 'journal')
            os.makedirs(photo_dir, exist_ok=True)
            photo_path = f"uploads/journal/{fname}"
            photo.save(os.path.join(STATIC_DIR, photo_path))
            
    entry = JournalEntry(trip_id=trip.id, user_id=current_user.id, title=title, 
                         content=content, date=date, tags=tags, is_favorite=is_fav, photo_path=photo_path)
    db.session.add(entry)
    db.session.commit()
    
    add_xp(current_user, 30, f"Saved journal entry: {title}")
    
    # Check unlock
    jcount = JournalEntry.query.filter_by(user_id=current_user.id).count()
    if jcount >= 3:
        check_and_unlock_achievement(current_user, "journal_master", "Chronicles of Travel")
        
    return redirect(url_for('trip_journal_view', trip_id=trip.id))

@app.route('/journal/entry/<int:entry_id>/delete')
@login_required
def delete_journal_entry(entry_id):
    entry = JournalEntry.query.get_or_404(entry_id)
    if entry.user_id != current_user.id: return "Unauthorized", 403
    trip_id = entry.trip_id
    db.session.delete(entry)
    db.session.commit()
    return redirect(url_for('trip_journal_view', trip_id=trip_id))

# --- Social Interaction Endpoints ---
@app.route('/trip/<int:trip_id>/like', methods=['POST'])
@login_required
def toggle_like(trip_id):
    trip = Trip.query.get_or_404(trip_id)
    like = Like.query.filter_by(user_id=current_user.id, trip_id=trip.id).first()
    if like:
        db.session.delete(like)
        liked = False
    else:
        new_like = Like(user_id=current_user.id, trip_id=trip.id)
        db.session.add(new_like)
        liked = True
        
        # Notify trip author and award social XP
        if trip.user_id != current_user.id:
            add_xp(trip.author, 15, f"Your trip '{trip.name}' was liked by {current_user.username}!")
            notif = Notification(user_id=trip.author.id, title="Trip Liked! ❤️", 
                                 content=f"{current_user.username} liked your itinerary '{trip.name}'.", 
                                 type="social")
            db.session.add(notif)
            
    db.session.commit()
    return jsonify({'success': True, 'liked': liked, 'likes_count': len(trip.likes)})

@app.route('/trip/<int:trip_id>/bookmark', methods=['POST'])
@login_required
def toggle_bookmark(trip_id):
    trip = Trip.query.get_or_404(trip_id)
    bk = Bookmark.query.filter_by(user_id=current_user.id, trip_id=trip.id).first()
    if bk:
        db.session.delete(bk)
        bookmarked = False
    else:
        new_bk = Bookmark(user_id=current_user.id, trip_id=trip.id)
        db.session.add(new_bk)
        bookmarked = True
        add_xp(current_user, 10, f"Bookmarked trip: {trip.name}")
        
    db.session.commit()
    return jsonify({'success': True, 'bookmarked': bookmarked})

@app.route('/trip/<int:trip_id>/comment', methods=['POST'])
@login_required
def add_comment(trip_id):
    trip = Trip.query.get_or_404(trip_id)
    content = request.form.get('content')
    if content:
        comm = Comment(user_id=current_user.id, trip_id=trip.id, content=content)
        db.session.add(comm)
        db.session.commit()
        add_xp(current_user, 5, "Added comment on trip")
        
        if trip.user_id != current_user.id:
            notif = Notification(user_id=trip.author.id, title="New Comment 💬", 
                                 content=f"{current_user.username} commented on '{trip.name}': {content[:40]}...", 
                                 type="social")
            db.session.add(notif)
            db.session.commit()
            
    return redirect(url_for('view_trip', trip_id=trip.id))

@app.route('/trip/<int:trip_id>/rate', methods=['POST'])
@login_required
def add_rating(trip_id):
    trip = Trip.query.get_or_404(trip_id)
    rating_val = int(request.form.get('rating', 5))
    
    # Check if user already rated
    r = Rating.query.filter_by(user_id=current_user.id, trip_id=trip.id).first()
    if r:
        r.rating = rating_val
    else:
        new_r = Rating(user_id=current_user.id, trip_id=trip.id, rating=rating_val)
        db.session.add(new_r)
        
    db.session.commit()
    add_xp(current_user, 5, "Rated trip")
    return redirect(url_for('view_trip', trip_id=trip.id))

@app.route('/user/<int:user_id>/follow', methods=['POST'])
@login_required
def toggle_follow(user_id):
    user_to_follow = User.query.get_or_404(user_id)
    if user_to_follow == current_user:
        return jsonify({'error': 'Cannot follow yourself'}), 400
        
    f = Follow.query.filter_by(follower_id=current_user.id, followed_id=user_to_follow.id).first()
    if f:
        db.session.delete(f)
        following = False
    else:
        new_f = Follow(follower_id=current_user.id, followed_id=user_to_follow.id)
        db.session.add(new_f)
        following = True
        
        # notify
        notif = Notification(user_id=user_to_follow.id, title="New Follower! 👤", 
                             content=f"{current_user.username} started following you.", 
                             type="social")
        db.session.add(notif)
        add_xp(user_to_follow, 20, f"Gained follower: {current_user.username}")
        
    db.session.commit()
    return jsonify({'success': True, 'following': following})

@app.route('/leaderboard')
def leaderboard_view():
    # Top users sorted by XP points
    top_users = User.query.order_by(User.xp.desc()).limit(10).all()
    # Trending Destinations (Cities with highest popularity logs)
    trending_cities = City.query.order_by(City.popularity.desc()).limit(5).all()
    return render_template('community.html', leaderboard=top_users, trending_cities=trending_cities, trips=Trip.query.filter_by(is_public=True).all())

# --- Smart Fuzzy Search and Typo Correct ---
@app.route('/api/search/smart')
def api_smart_search():
    q = request.args.get('q', '').strip()
    category = request.args.get('category', '').strip()
    max_budget = request.args.get('budget', '').strip()
    max_budget = float(max_budget) if max_budget else None
    
    # Save search logs
    if current_user.is_authenticated and q:
        slog = SearchHistory(user_id=current_user.id, query=q)
        db.session.add(slog)
        db.session.commit()

    query_builder = Trip.query.filter(Trip.is_public == True)
    
    if q:
        # Smart search: filter by destination or name
        # We can implement basic SQL LIKE fuzzy matches
        query_builder = query_builder.filter(
            (Trip.destination.ilike(f"%{q}%")) | 
            (Trip.name.ilike(f"%{q}%"))
        )
    if category:
        query_builder = query_builder.filter(Trip.style == category)
    if max_budget is not None:
        query_builder = query_builder.filter(Trip.estimated_budget <= max_budget)
        
    results = query_builder.all()
    
    payload = []
    for r in results:
        payload.append({
            'id': r.id,
            'name': r.name,
            'destination': r.destination,
            'budget': r.estimated_budget,
            'style': r.style,
            'author': r.author.username,
            'likes': len(r.likes)
        })
        
    return jsonify({'results': payload})

# --- Offline Places UI Maps ---
@app.route('/trip/<int:trip_id>/places')
@login_required
def trip_places_view(trip_id):
    trip = Trip.query.get_or_404(trip_id)
    if trip.user_id != current_user.id: return "Unauthorized", 403
    return render_template('maps.html', trip=trip)

@app.route('/trip/<int:trip_id>/places/add', methods=['POST'])
@login_required
def trip_places_add(trip_id):
    trip = Trip.query.get_or_404(trip_id)
    if trip.user_id != current_user.id: return "Unauthorized", 403
    
    name = request.form.get('name')
    lat = float(request.form.get('lat') or 0.0)
    lng = float(request.form.get('lng') or 0.0)
    category = request.form.get('category', 'Sightseeing')
    notes = request.form.get('notes')
    contact = request.form.get('contact')
    
    place = PlaceOfInterest(trip_id=trip.id, name=name, lat=lat, lng=lng, category=category, notes=notes, contact=contact)
    db.session.add(place)
    db.session.commit()
    
    add_xp(current_user, 10, f"Added local stop marker {name}")
    return redirect(url_for('trip_places_view', trip_id=trip.id))

@app.route('/place/<int:place_id>/delete')
@login_required
def delete_place(place_id):
    place = PlaceOfInterest.query.get_or_404(place_id)
    if place.trip.user_id != current_user.id: return "Unauthorized", 403
    trip_id = place.trip_id
    db.session.delete(place)
    db.session.commit()
    return redirect(url_for('trip_places_view', trip_id=trip_id))

# --- Document Export Handlers ---
@app.route('/trip/<int:trip_id>/export/pdf')
def export_trip_pdf(trip_id):
    trip = Trip.query.get_or_404(trip_id)
    if not trip.is_public and (not current_user.is_authenticated or trip.user_id != current_user.id):
        return "Unauthorized", 403
        
    pdf_buffer = generate_itinerary_pdf(trip)
    filename = f"{secure_filename(trip.name)}_itinerary.pdf"
    
    if current_user.is_authenticated:
        add_xp(current_user, 15, f"Exported PDF copy of trip: {trip.name}")
        
    return send_file(
        pdf_buffer,
        as_attachment=True,
        download_name=filename,
        mimetype='application/pdf'
    )

@app.route('/trip/<int:trip_id>/export/expenses')
@login_required
def export_trip_expenses(trip_id):
    trip = Trip.query.get_or_404(trip_id)
    if trip.user_id != current_user.id: return "Unauthorized", 403
    
    csv_file = generate_expenses_csv(trip, trip.expenses)
    
    # Convert StringIO to bytes for flask send_file
    mem = io.BytesIO()
    mem.write(csv_file.getvalue().encode('utf-8'))
    mem.seek(0)
    
    filename = f"{secure_filename(trip.name)}_expenses.csv"
    add_xp(current_user, 15, f"Exported expenses sheet of trip: {trip.name}")
    
    return send_file(
        mem,
        as_attachment=True,
        download_name=filename,
        mimetype='text/csv'
    )

# --- Notification REST APIs ---
@app.route('/api/notifications')
@login_required
def api_notifications():
    notifs = Notification.query.filter_by(user_id=current_user.id).order_by(Notification.created_at.desc()).limit(15).all()
    payload = []
    for n in notifs:
        payload.append({
            'id': n.id,
            'title': n.title,
            'content': n.content,
            'type': n.type,
            'is_read': n.is_read,
            'time': n.created_at.strftime('%m-%d %H:%M')
        })
    return jsonify(payload)

@app.route('/api/notifications/read/<int:notif_id>', methods=['POST'])
@login_required
def api_mark_read(notif_id):
    notif = Notification.query.get_or_404(notif_id)
    if notif.user_id != current_user.id: return jsonify({'error': 'unauthorized'}), 403
    notif.is_read = True
    db.session.commit()
    return jsonify({'success': True})

# --- Standard App Views & Copy Function Overrides ---
@app.route('/search/cities')
def search_cities():
    q = request.args.get('q','')
    if q:
        results = City.query.filter(City.name.ilike(f"%{q}%")).limit(20).all()
    else:
        results = City.query.limit(20).all()
    out = [{'id':c.id,'name':c.name,'country':c.country,'cost_index':c.cost_index} for c in results]
    return {'results': out}

@app.route('/search/activities')
def search_activities():
    q = request.args.get('q','')
    if q:
        results = Activity.query.filter(Activity.title.ilike(f"%{q}%")).limit(30).all()
    else:
        results = Activity.query.limit(30).all()
    out = [{'id':a.id,'title':a.title,'cost':a.cost,'category':a.category} for a in results]
    return {'results': out}

@app.route('/trip/<int:trip_id>/builder')
@login_required
def itinerary_builder_view(trip_id):
    trip = Trip.query.get_or_404(trip_id)
    if trip.user_id != current_user.id:
        flash('You do not have permission to edit this itinerary.')
        return redirect(url_for('view_trip', trip_id=trip.id))
    return render_template('itinerary_builder.html', trip=trip)

@app.route('/api/trip/<int:trip_id>')
def api_get_trip(trip_id):
    trip = Trip.query.get_or_404(trip_id)
    if not trip.is_public and (not current_user.is_authenticated or trip.user_id != current_user.id):
        return jsonify({'error': 'forbidden'}), 403
    stops = []
    for s in sorted(trip.stops, key=lambda x: x.ord or 0):
        stops.append({
            'id': s.id,
            'city': {'id': s.city.id, 'name': s.city.name, 'country': s.city.country},
            'arrival': s.arrival.isoformat() if s.arrival else None,
            'depart': s.depart.isoformat() if s.depart else None,
            'activities': [
                {'id': a.id, 'title': a.title, 'description': a.description, 'cost': a.cost, 'duration_hours': a.duration_hours, 'category': a.category}
                for a in s.activities
            ]
        })
    sections = [
        {'id': sec.id, 'title': sec.title, 'activity': sec.activity, 'budget': sec.budget, 'date': sec.date.isoformat() if sec.date else None}
        for sec in trip.sections
    ]
    payload = {
        'id': trip.id,
        'name': trip.name,
        'destination': trip.destination,
        'start_date': trip.start_date.isoformat(),
        'end_date': trip.end_date.isoformat(),
        'is_public': trip.is_public,
        'author': {'id': trip.author.id, 'username': trip.author.username},
        'stops': stops,
        'sections': sections
    }
    return jsonify(payload)

@app.route('/api/trip/<int:trip_id>/budget')
def api_trip_budget(trip_id):
    trip = Trip.query.get_or_404(trip_id)
    if not trip.is_public and (not current_user.is_authenticated or trip.user_id != current_user.id):
        return jsonify({'error': 'forbidden'}), 403
        
    section_cost = sum((s.budget or 0) for s in trip.sections)
    activity_cost = sum((a.cost or 0) for s in trip.stops for a in s.activities)
    expense_cost = sum((e.amount or 0) for e in trip.expenses)
    total = section_cost + activity_cost + expense_cost
    
    estimated = trip.estimated_budget or 0.0
    balance = estimated - total
    status = 'none'
    over_by = 0.0
    if estimated > 0:
        if balance < 0:
            status = 'over'
            over_by = abs(balance)
        else:
            status = 'under'
            
    breakdown = {
        'trip_id': trip.id,
        'section_cost': section_cost,
        'activity_cost': activity_cost,
        'expense_cost': expense_cost,
        'total': total,
        'estimated_budget': estimated,
        'balance': balance,
        'status': status,
        'over_by': over_by,
        'average_per_day': (total / ((trip.end_date - trip.start_date).days + 1)) if trip.end_date >= trip.start_date else total
    }
    return jsonify(breakdown)

@app.route('/my_trips')
@login_required
def my_trips():
    trips = Trip.query.filter_by(user_id=current_user.id).order_by(Trip.start_date).all()
    return render_template('calendar.html', trips=trips, title="My Trips")

@app.route('/community')
def community():
    public_trips = Trip.query.filter_by(is_public=True).all()
    top_users = User.query.order_by(User.xp.desc()).limit(5).all()
    trending_cities = City.query.order_by(City.popularity.desc()).limit(5).all()
    return render_template('community.html', trips=public_trips, leaderboard=top_users, trending_cities=trending_cities)

@app.route('/calendar')
@login_required
def calendar_view():
    trips = Trip.query.filter_by(user_id=current_user.id).order_by(Trip.start_date).all()
    return render_template('calendar.html', trips=trips, title="Calendar View")

@app.route('/trip/<int:trip_id>/copy')
@login_required
def copy_trip(trip_id):
    orig = Trip.query.get_or_404(trip_id)
    if not orig.is_public and orig.user_id != current_user.id:
        flash('Cannot copy private trip')
        return redirect(url_for('view_trip', trip_id=trip_id))
        
    # Duplicate Trip
    new_trip = Trip(name=f"Copy of {orig.name}", destination=orig.destination,
                    start_date=orig.start_date, end_date=orig.end_date,
                    is_public=False, estimated_budget=orig.estimated_budget, 
                    style=orig.style, author=current_user)
    db.session.add(new_trip)
    db.session.flush()
    
    # Copy items
    for sec in orig.sections:
        ns = TripSection(trip_id=new_trip.id, title=sec.title, activity=sec.activity, budget=sec.budget, date=sec.date)
        db.session.add(ns)
    for stop in orig.stops:
        ns = Stop(trip_id=new_trip.id, city_id=stop.city_id, arrival=stop.arrival, depart=stop.depart, ord=stop.ord)
        db.session.add(ns)
        db.session.flush()
        for a in stop.activities:
            na = Activity(stop_id=ns.id, title=a.title, description=a.description, cost=a.cost, duration_hours=a.duration_hours, category=a.category)
            db.session.add(na)
    for exp in orig.expenses:
        ne = Expense(trip_id=new_trip.id, title=exp.title, amount=exp.amount, category=exp.category, date=exp.date, description=exp.description)
        db.session.add(ne)
        
    db.session.commit()
    add_xp(current_user, 20, f"Cloned community trip '{orig.name}'")
    flash('Trip copied to your account')
    return redirect(url_for('view_trip', trip_id=new_trip.id))

@app.route('/admin')
@login_required
def admin_panel():
    if not current_user.is_admin: return "Access Denied", 403
    stats = {
        'user_count': User.query.count(),
        'trip_count': Trip.query.count(),
        'public_trip_count': Trip.query.filter_by(is_public=True).count(),
        'users': User.query.all()
    }
    return render_template('admin.html', **stats)

@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    user = current_user
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')
        if username: user.username = username
        if email: user.email = email
        if password:
            user.password = generate_password_hash(password, method='pbkdf2:sha256')
        db.session.commit()
        flash('Profile updated')
        return redirect(url_for('profile'))
        
    # Unlocked badges grid
    badges = UserAchievement.query.filter_by(user_id=user.id).all()
    
    # Travel statistics
    trips_count = Trip.query.filter_by(user_id=user.id).count()
    visited_cities = City.query.join(Stop).join(Trip).filter(Trip.user_id == user.id).distinct().count()
    total_xp = user.xp or 0
    level = user.level or 1
    
    return render_template('profile.html', user=user, badges=badges, trips_count=trips_count, visited_cities=visited_cities, xp=total_xp, level=level)


# --- SQLite Auto Migration & Seeding ---
with app.app_context():
    db.create_all()
    
    # Ensure older database migrations run successfully
    try:
        res = db.session.execute(text("PRAGMA table_info('user')")).fetchall()
        cols = [r[1] for r in res]
        if 'xp' not in cols:
            db.session.execute(text("ALTER TABLE user ADD COLUMN xp INTEGER DEFAULT 0"))
            db.session.execute(text("ALTER TABLE user ADD COLUMN level INTEGER DEFAULT 1"))
            db.session.execute(text("ALTER TABLE user ADD COLUMN points INTEGER DEFAULT 0"))
            db.session.commit()
            print("Migrated User tables with XP/points elements.")
    except Exception as e:
        print("User migration warning:", e)
        
    try:
        res = db.session.execute(text("PRAGMA table_info('trip')")).fetchall()
        cols = [r[1] for r in res]
        if 'estimated_budget' not in cols:
            db.session.execute(text("ALTER TABLE trip ADD COLUMN estimated_budget REAL DEFAULT 0.0"))
        if 'style' not in cols:
            db.session.execute(text("ALTER TABLE trip ADD COLUMN style VARCHAR(50) DEFAULT 'Solo'"))
        db.session.commit()
    except Exception as e:
        print("Trip migration warning:", e)
        
    def seed_data():
        if City.query.count() == 0:
            cities = [
                City(name='Paris', country='France', cost_index=1.4, popularity=95),
                City(name='Tokyo', country='Japan', cost_index=1.6, popularity=120),
                City(name='Lisbon', country='Portugal', cost_index=1.0, popularity=88),
                City(name='Bali', country='Indonesia', cost_index=0.6, popularity=150),
                City(name='New York', country='USA', cost_index=1.8, popularity=110)
            ]
            db.session.add_all(cities)
            db.session.commit()
    try:
        seed_data()
    except Exception:
        pass

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5001))
    app.run(debug=True, port=port)