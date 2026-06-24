import os
import sys
from datetime import datetime, date

# Append app.py folder to sys.path
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'app.py'))

from app import app, db, User, Trip, Expense
from ai_engine import ai_engine
from exporter import generate_itinerary_pdf, generate_expenses_csv

def test_database_and_models():
    print("Testing Database initialization...")
    with app.app_context():
        db.create_all()
        # Verify seeding or simple insertions
        test_user = User.query.filter_by(username="test_traveler").first()
        if not test_user:
            test_user = User(username="test_traveler", email="test@globetrotter.com", password="hash", xp=0, level=1)
            db.session.add(test_user)
            db.session.commit()
            print("Successfully inserted test user.")
        else:
            print("Test user already exists.")
            
        test_trip = Trip.query.filter_by(name="Test Trip").first()
        if not test_trip:
            test_trip = Trip(name="Test Trip", destination="Paris", start_date=date(2026, 7, 1), end_date=date(2026, 7, 5), estimated_budget=1500.0, author=test_user)
            db.session.add(test_trip)
            db.session.commit()
            print("Successfully inserted test trip.")
        else:
            print("Test trip already exists.")
            
        # Add basic expense
        exp = Expense(trip_id=test_trip.id, title="Eiffel ticket", amount=25.0, category="Activities")
        db.session.add(exp)
        db.session.commit()
        print("Successfully logged a test expense.")

def test_ai_connections():
    print("\nTesting local AI Ollama connection...")
    if ai_engine.is_available():
        print("SUCCESS: Local Ollama check verified.")
        print(f"Ollama Model active: {ai_engine.embeddings.model if ai_engine.embeddings else 'None'}")
        
        # Test basic completion query
        ans = ai_engine.query_ollama("Return 'Ollama connected!' in exactly 2 words.")
        print(f"Test Completion Response: {ans.strip()}")
    else:
        print("WARNING: Local Ollama is not active or reachable. Operating in mock response mode.")
        ans = ai_engine.query_ollama("Return 'Ollama connected!'")
        print(f"Mock Response: {ans.strip()}")

def test_pdf_compilation():
    print("\nTesting ReportLab PDF compile...")
    with app.app_context():
        trip = Trip.query.filter_by(name="Test Trip").first()
        if trip:
            pdf_stream = generate_itinerary_pdf(trip)
            pdf_size = len(pdf_stream.getvalue())
            print(f"SUCCESS: ReportLab successfully compiled PDF ({pdf_size} bytes).")
        else:
            print("FAILED: No trip available to compile PDF.")

if __name__ == '__main__':
    print("=========================================")
    print("GLOBETROTTER INTEGRATED SYSTEMS TEST")
    print("=========================================")
    try:
        test_database_and_models()
        test_ai_connections()
        test_pdf_compilation()
        print("\nAll systems checks completed successfully!")
    except Exception as e:
        print(f"\nCRITICAL FAILURE during systems test: {e}")
        sys.exit(1)
