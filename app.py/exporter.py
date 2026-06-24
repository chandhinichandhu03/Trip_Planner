import os
import csv
import io
from datetime import datetime
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
from reportlab.lib.units import inch

def generate_itinerary_pdf(trip):
    """
    Generate a styled PDF itinerary for the given Trip.
    Returns a BytesIO stream containing the PDF.
    """
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=54, leftMargin=54, topMargin=54, bottomMargin=54
    )
    
    styles = getSampleStyleSheet()
    
    # Custom Palette (Teal Branding)
    primary_color = colors.HexColor('#008080')
    secondary_color = colors.HexColor('#20c997')
    dark_neutral = colors.HexColor('#2d3748')
    light_neutral = colors.HexColor('#f7fafc')
    accent_color = colors.HexColor('#e53e3e')
    
    # Custom styles
    title_style = ParagraphStyle(
        'TripTitle',
        parent=styles['Heading1'],
        fontName='Helvetica-Bold',
        fontSize=24,
        leading=28,
        textColor=primary_color,
        spaceAfter=6
    )
    
    subtitle_style = ParagraphStyle(
        'TripSubtitle',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=12,
        textColor=colors.HexColor('#718096'),
        spaceAfter=15
    )
    
    heading_style = ParagraphStyle(
        'SectionHeading',
        parent=styles['Heading2'],
        fontName='Helvetica-Bold',
        fontSize=15,
        leading=18,
        textColor=dark_neutral,
        spaceBefore=12,
        spaceAfter=6
    )
    
    body_style = ParagraphStyle(
        'Body',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=10,
        leading=14,
        textColor=dark_neutral
    )

    bold_body_style = ParagraphStyle(
        'BoldBody',
        parent=body_style,
        fontName='Helvetica-Bold'
    )
    
    story = []
    
    # Header
    story.append(Paragraph(f"{trip.name}", title_style))
    story.append(Paragraph(f"Destination: {trip.destination}  |  Dates: {trip.start_date} to {trip.end_date}", subtitle_style))
    story.append(Spacer(1, 10))
    
    # Budget Summary Info Table
    estimated = getattr(trip, 'estimated_budget', 0.0) or 0.0
    section_cost = sum((s.budget or 0) for s in trip.sections)
    activity_cost = sum((a.cost or 0) for s in trip.stops for a in s.activities)
    total_cost = section_cost + activity_cost
    balance = estimated - total_cost
    
    summary_data = [
        [Paragraph("Estimated Budget", bold_body_style), Paragraph(f"${estimated:,.2f}", body_style)],
        [Paragraph("Section Allocations", bold_body_style), Paragraph(f"${section_cost:,.2f}", body_style)],
        [Paragraph("Activity Expenses", bold_body_style), Paragraph(f"${activity_cost:,.2f}", body_style)],
        [Paragraph("Total Planned Cost", bold_body_style), Paragraph(f"${total_cost:,.2f}", body_style)],
        [Paragraph("Remaining Balance", bold_body_style), Paragraph(f"${balance:,.2f}", body_style)]
    ]
    
    t = Table(summary_data, colWidths=[2.5 * inch, 3.5 * inch])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), light_neutral),
        ('ALIGN', (0,0), (-1,-1), 'LEFT'),
        ('TEXTCOLOR', (0,0), (-1,-1), dark_neutral),
        ('BOTTOMPADDING', (0,0), (-1,-1), 6),
        ('TOPPADDING', (0,0), (-1,-1), 6),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#e2e8f0')),
    ]))
    
    story.append(Paragraph("Financial Summary", heading_style))
    story.append(t)
    story.append(Spacer(1, 15))
    
    # Stops / Multi-City Route
    if trip.stops:
        story.append(Paragraph("Travel Route & Stops", heading_style))
        route_data = [[Paragraph("City", bold_body_style), Paragraph("Arrival", bold_body_style), Paragraph("Departure", bold_body_style)]]
        for stop in sorted(trip.stops, key=lambda x: x.ord or 0):
            arr = stop.arrival.strftime('%Y-%m-%d') if stop.arrival else "N/A"
            dep = stop.depart.strftime('%Y-%m-%d') if stop.depart else "N/A"
            route_data.append([
                Paragraph(f"{stop.city.name}, {stop.city.country or ''}", body_style),
                Paragraph(arr, body_style),
                Paragraph(dep, body_style)
            ])
            
        rt_table = Table(route_data, colWidths=[3 * inch, 1.5 * inch, 1.5 * inch])
        rt_table.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), primary_color),
            ('TEXTCOLOR', (0,0), (-1,0), colors.white),
            ('ALIGN', (0,0), (-1,-1), 'LEFT'),
            ('BOTTOMPADDING', (0,0), (-1,-1), 6),
            ('TOPPADDING', (0,0), (-1,-1), 6),
            ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#cbd5e0')),
        ]))
        
        # Override table header text colors for Paragraphs
        for i in range(3):
            route_data[0][i].style.textColor = colors.white
            
        story.append(rt_table)
        story.append(Spacer(1, 15))
        
        # Day-by-Day Activities
        story.append(Paragraph("Scheduled Activities", heading_style))
        for stop in sorted(trip.stops, key=lambda x: x.ord or 0):
            if stop.activities:
                story.append(Paragraph(f"Activities in {stop.city.name}", ParagraphStyle('CitySub', parent=styles['Heading3'], textColor=primary_color, spaceBefore=8, spaceAfter=4)))
                for act in stop.activities:
                    act_desc = f"<b>{act.title}</b>"
                    if act.category:
                        act_desc += f" (Category: {act.category})"
                    if act.duration_hours:
                        act_desc += f" | Duration: {act.duration_hours} hrs"
                    act_desc += f" | Cost: ${act.cost:.2f}"
                    
                    story.append(Paragraph(act_desc, body_style))
                    if act.description:
                        story.append(Paragraph(f"<font color='#4a5568'><i>{act.description}</i></font>", ParagraphStyle('Desc', parent=body_style, leftIndent=12, spaceAfter=4)))
                    story.append(Spacer(1, 4))
        story.append(Spacer(1, 10))

    # General Sections
    if trip.sections:
        story.append(Paragraph("General Plan Sections", heading_style))
        for sec in sorted(trip.sections, key=lambda x: x.date or datetime.min.date()):
            sec_date = sec.date.strftime('%Y-%m-%d') if sec.date else "Anytime"
            sec_title = f"<b>{sec.title}</b> ({sec_date}) - Budget: ${sec.budget:.2f}"
            story.append(Paragraph(sec_title, body_style))
            story.append(Paragraph(f"<font color='#4a5568'>{sec.activity}</font>", ParagraphStyle('SecAct', parent=body_style, leftIndent=12, spaceAfter=8)))
            
    doc.build(story)
    buffer.seek(0)
    return buffer

def generate_expenses_csv(trip, expenses):
    """
    Generate a CSV formatted expense report.
    Returns a StringIO containing CSV data.
    """
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Headers
    writer.writerow([f"Expense Report for Trip: {trip.name}"])
    writer.writerow(["Destination", trip.destination])
    writer.writerow(["Start Date", trip.start_date])
    writer.writerow(["End Date", trip.end_date])
    writer.writerow(["Estimated Budget", f"${trip.estimated_budget:.2f}" if trip.estimated_budget else "$0.00"])
    writer.writerow([])
    
    # Table headers
    writer.writerow(["Date", "Title/Description", "Category", "Amount ($)"])
    
    total_spent = 0.0
    for exp in sorted(expenses, key=lambda x: x.date or datetime.min.date()):
        dt = exp.date.strftime('%Y-%m-%d') if exp.date else "N/A"
        writer.writerow([dt, exp.title, exp.category, f"{exp.amount:.2f}"])
        total_spent += exp.amount
        
    writer.writerow([])
    writer.writerow(["", "", "Total Spent", f"${total_spent:.2f}"])
    
    if trip.estimated_budget:
        balance = trip.estimated_budget - total_spent
        writer.writerow(["", "", "Remaining Balance", f"${balance:.2f}"])
        
    output.seek(0)
    return output
