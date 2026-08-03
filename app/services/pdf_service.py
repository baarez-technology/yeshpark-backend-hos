"""
PDF generation service for booking confirmations
"""
import logging
from io import BytesIO
from typing import Dict, Any
from datetime import datetime
try:
    from reportlab.lib.pagesizes import letter, A4
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    REPORTLAB_AVAILABLE = True
except ImportError:
    REPORTLAB_AVAILABLE = False
    # Fallback: create a simple text-based PDF using basic libraries
    pass

logger = logging.getLogger(__name__)


def generate_booking_confirmation_pdf(booking_data: Dict[str, Any]) -> bytes:
    """
    Generate booking confirmation PDF
    
    Args:
        booking_data: Dictionary containing booking information
        
    Returns:
        bytes: PDF file content
    """
    if not REPORTLAB_AVAILABLE:
        # Fallback: return empty bytes or use alternative method
        logger.warning("ReportLab not available, using fallback PDF generation")
        return _generate_simple_pdf(booking_data)
    
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter)
    story = []
    styles = getSampleStyleSheet()
    
    # Custom styles
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=24,
        textColor=colors.HexColor('#A57865'),
        spaceAfter=30,
        alignment=1,  # Center
    )
    
    heading_style = ParagraphStyle(
        'CustomHeading',
        parent=styles['Heading2'],
        fontSize=16,
        textColor=colors.HexColor('#A57865'),
        spaceAfter=12,
    )
    
    # Header
    story.append(Paragraph("GLIMMORA HOTEL", title_style))
    story.append(Paragraph("Booking Confirmation", styles['Heading2']))
    story.append(Spacer(1, 0.3*inch))
    
    # Confirmation Number
    story.append(Paragraph(
        f"<b>Confirmation Number:</b> {booking_data.get('booking_number', 'N/A')}",
        styles['Normal']
    ))
    story.append(Spacer(1, 0.2*inch))
    
    # Booking Details
    story.append(Paragraph("Reservation Details", heading_style))
    
    details_data = [
        ['Guest Name:', f"{booking_data.get('guest_name', 'N/A')}"],
        ['Email:', booking_data.get('email', 'N/A')],
        ['Phone:', booking_data.get('phone', 'N/A')],
        ['Check-in:', booking_data.get('check_in', 'N/A')],
        ['Check-out:', booking_data.get('check_out', 'N/A')],
        ['Duration:', f"{booking_data.get('nights', 0)} night(s)"],
        ['Room Type:', booking_data.get('room_type', 'N/A')],
    ]
    
    if booking_data.get('room_number'):
        details_data.append(['Room Number:', booking_data.get('room_number')])
    
    details_table = Table(details_data, colWidths=[2*inch, 4*inch])
    details_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#F5F5F5')),
        ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
    ]))
    story.append(details_table)
    story.append(Spacer(1, 0.3*inch))
    
    # Pricing
    story.append(Paragraph("Pricing Summary", heading_style))
    
    currency = booking_data.get('currency', '₹')
    pricing_data = [
        ['Item', 'Amount'],
        ['Base Price', f"{currency}{booking_data.get('base_price', 0):.2f}"],
        ['Taxes', f"{currency}{booking_data.get('taxes', 0):.2f}"],
        ['Total', f"<b>{currency}{booking_data.get('total_amount', 0):.2f}</b>"],
    ]
    
    pricing_table = Table(pricing_data, colWidths=[4*inch, 2*inch])
    pricing_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#A57865')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('ALIGN', (1, 1), (1, -1), 'RIGHT'),
    ]))
    story.append(pricing_table)
    story.append(Spacer(1, 0.3*inch))
    
    # Footer
    story.append(Spacer(1, 0.5*inch))
    story.append(Paragraph(
        "Thank you for choosing Glimmora Hotel!",
        ParagraphStyle('Footer', parent=styles['Normal'], alignment=1)
    ))
    story.append(Paragraph(
        "For questions, contact: reservations@glimmora.com",
        ParagraphStyle('Footer', parent=styles['Normal'], fontSize=8, alignment=1, textColor=colors.grey)
    ))
    
    # Build PDF
    doc.build(story)
    buffer.seek(0)
    return buffer.getvalue()


def generate_invoice_pdf(booking_data: Dict[str, Any]) -> bytes:
    """
    Generate a professional hotel invoice PDF.

    Args:
        booking_data: Dictionary with keys: booking_number, guest_name, email, phone,
            check_in, check_out, nights, room_type, room_number, base_price, taxes,
            service_fee, total_amount, payment_status, payment_method, amount_paid,
            balance_due, invoice_date, hotel_name
    """
    if not REPORTLAB_AVAILABLE:
        logger.warning("ReportLab not available for invoice generation")
        return _generate_simple_pdf(booking_data)

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4,
                            topMargin=0.5*inch, bottomMargin=0.5*inch,
                            leftMargin=0.6*inch, rightMargin=0.6*inch)
    story = []
    styles = getSampleStyleSheet()

    terra = colors.HexColor('#A57865')
    dark = colors.HexColor('#1A1A1A')
    grey_bg = colors.HexColor('#F5F5F5')
    light_border = colors.HexColor('#E5E5E5')

    title_style = ParagraphStyle('InvTitle', parent=styles['Heading1'],
        fontSize=26, textColor=terra, spaceAfter=4, alignment=0)
    subtitle_style = ParagraphStyle('InvSub', parent=styles['Normal'],
        fontSize=10, textColor=colors.grey, spaceAfter=20)
    heading_style = ParagraphStyle('InvHead', parent=styles['Heading2'],
        fontSize=13, textColor=terra, spaceAfter=10, spaceBefore=16)
    label_style = ParagraphStyle('InvLabel', parent=styles['Normal'],
        fontSize=9, textColor=colors.grey)
    value_style = ParagraphStyle('InvValue', parent=styles['Normal'],
        fontSize=10, textColor=dark)

    hotel_name = booking_data.get('hotel_name', 'Glimmora Hotel & Suites')
    invoice_no = f"INV-{booking_data.get('booking_number', 'N/A')}"
    invoice_date = booking_data.get('invoice_date', datetime.utcnow().strftime('%B %d, %Y'))

    # Header
    story.append(Paragraph(hotel_name.upper(), title_style))
    story.append(Paragraph(f"Invoice #{invoice_no}  |  {invoice_date}", subtitle_style))

    # Divider
    divider_table = Table([['']],  colWidths=[6.8*inch])
    divider_table.setStyle(TableStyle([
        ('LINEBELOW', (0, 0), (-1, 0), 1.5, terra),
    ]))
    story.append(divider_table)
    story.append(Spacer(1, 0.2*inch))

    # Guest & Stay details side by side
    guest_name = booking_data.get('guest_name', 'N/A')
    email = booking_data.get('email', '')
    phone = booking_data.get('phone', '')
    check_in = booking_data.get('check_in', 'N/A')
    check_out = booking_data.get('check_out', 'N/A')
    nights = booking_data.get('nights', 0)
    room_type = booking_data.get('room_type', 'N/A')
    room_number = booking_data.get('room_number', 'N/A')

    left_col = [
        [Paragraph('<b>Bill To</b>', value_style)],
        [Paragraph(guest_name, ParagraphStyle('GN', parent=value_style, fontSize=12, leading=14))],
        [Paragraph(email, label_style)] if email else [],
        [Paragraph(phone, label_style)] if phone else [],
    ]
    left_col = [r for r in left_col if r]

    right_col = [
        [Paragraph('<b>Stay Details</b>', value_style)],
        [Paragraph(f'Check-in: {check_in}', value_style)],
        [Paragraph(f'Check-out: {check_out}', value_style)],
        [Paragraph(f'{nights} night(s)  |  Room {room_number}  |  {room_type}', label_style)],
    ]

    max_rows = max(len(left_col), len(right_col))
    while len(left_col) < max_rows:
        left_col.append([''])
    while len(right_col) < max_rows:
        right_col.append([''])

    info_data = []
    for i in range(max_rows):
        lv = left_col[i][0] if left_col[i] else ''
        rv = right_col[i][0] if right_col[i] else ''
        info_data.append([lv, '', rv])

    info_table = Table(info_data, colWidths=[3*inch, 0.8*inch, 3*inch])
    info_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('TOPPADDING', (0, 0), (-1, -1), 2),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
    ]))
    story.append(info_table)
    story.append(Spacer(1, 0.25*inch))

    # Charges table
    story.append(Paragraph("Charges", heading_style))

    base_price = booking_data.get('base_price', 0)
    taxes = booking_data.get('taxes', 0)
    total = booking_data.get('total_amount', 0)
    amount_paid = booking_data.get('amount_paid', 0)
    balance_due = booking_data.get('balance_due', total - amount_paid)

    currency = booking_data.get('currency', '₹')
    charges = [
        ['Description', 'Amount'],
        [f'Room Charges ({nights} night(s) x {currency}{base_price / nights:.2f}/night)' if nights > 0 else 'Room Charges', f'{currency}{base_price:.2f}'],
        ['Taxes & Fees', f'{currency}{taxes:.2f}'],
    ]

    charges_table = Table(charges, colWidths=[5*inch, 1.8*inch])
    charges_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), terra),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
        ('TOPPADDING', (0, 0), (-1, -1), 10),
        ('LEFTPADDING', (0, 0), (-1, -1), 12),
        ('RIGHTPADDING', (0, 0), (-1, -1), 12),
        ('GRID', (0, 0), (-1, -1), 0.5, light_border),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, grey_bg]),
    ]))
    story.append(charges_table)
    story.append(Spacer(1, 0.15*inch))

    # Totals
    payment_method = (booking_data.get('payment_method') or 'N/A').replace('_', ' ').title()
    payment_status = (booking_data.get('payment_status') or 'pending').title()

    totals = [
        ['Total', f'{currency}{total:.2f}'],
        [f'Paid ({payment_method})', f'{currency}{amount_paid:.2f}'],
        ['Balance Due', f'{currency}{balance_due:.2f}'],
    ]
    totals_table = Table(totals, colWidths=[5*inch, 1.8*inch])
    totals_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('LEFTPADDING', (0, 0), (-1, -1), 12),
        ('RIGHTPADDING', (0, 0), (-1, -1), 12),
        ('LINEABOVE', (0, 0), (-1, 0), 1.5, terra),
        ('LINEBELOW', (0, -1), (-1, -1), 1.5, terra),
        ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#FDF2EE')),
        ('TEXTCOLOR', (0, -1), (-1, -1), terra),
        ('FONTSIZE', (0, -1), (-1, -1), 12),
    ]))
    story.append(totals_table)
    story.append(Spacer(1, 0.15*inch))

    # Payment status badge
    story.append(Paragraph(f"Payment Status: <b>{payment_status}</b>", value_style))
    story.append(Spacer(1, 0.5*inch))

    # Footer
    footer_style = ParagraphStyle('InvFooter', parent=styles['Normal'],
        fontSize=8, textColor=colors.grey, alignment=1)
    story.append(Paragraph("Thank you for staying with us!", ParagraphStyle(
        'Thanks', parent=styles['Normal'], fontSize=11, alignment=1, textColor=terra)))
    story.append(Spacer(1, 0.15*inch))
    story.append(Paragraph(f"{hotel_name}  |  reservations@glimmora.com", footer_style))
    story.append(Paragraph("This is a computer-generated invoice.", footer_style))

    doc.build(story)
    buffer.seek(0)
    return buffer.getvalue()


def _generate_simple_pdf(booking_data: Dict[str, Any]) -> bytes:
    """
    Fallback simple PDF generation (if ReportLab not available)
    Creates a basic text-based PDF
    """
    # For now, return empty bytes - in production, implement alternative PDF generation
    # or ensure ReportLab is installed
    import logging
    logging.warning("Simple PDF generation not implemented - install ReportLab")
    return b''

