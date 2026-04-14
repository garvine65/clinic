from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_http_methods
from django.contrib import messages
from django.db import transaction
from .models import PatientProfile, ClinicalAssessment, Appointment, SessionRecord, Document
from django.utils import timezone
from datetime import timedelta
from typing import TYPE_CHECKING
from django.http import FileResponse
import mimetypes

if TYPE_CHECKING:
    from django.db.models import QuerySet

# ============= PUBLIC VIEWS =============
def home(request):
    """Landing page for the clinic."""
    # Get all downloadable documents
    documents = Document.objects.all()
    
    # Create a dictionary for easy template access
    docs_dict = {doc.document_type: doc for doc in documents}
    
    context = {
        'consent_doc': docs_dict.get('consent'),
        'biodata_doc': docs_dict.get('biodata'),
        'contract_doc': docs_dict.get('contract'),
        'all_documents': documents,
    }
    
    return render(request, 'clinic/home.html', context)


def book_appointment_redirect(request):
    """Redirect to booking system. Shows login message if not authenticated."""
    if request.user.is_authenticated:
        return redirect('booking_calendar')
    else:
        messages.info(request, "You must be logged in to book an appointment. Please sign in or create an account.")
        return redirect('patient_login')


def download_document(request, doc_type):
    """Download a document by type (consent, biodata, contract)."""
    document = get_object_or_404(Document, document_type=doc_type)
    
    if not document.file:
        messages.error(request, "This document is not yet available. Please check back soon.")
        return redirect('home')
    
    try:
        file_path = document.file.path
        file = open(file_path, 'rb')
        mime_type, _ = mimetypes.guess_type(file_path)
        
        response = FileResponse(file, content_type=mime_type or 'application/octet-stream')
        response['Content-Disposition'] = f'attachment; filename="{document.title}.pdf"'
        return response
    except Exception as e:
        messages.error(request, f"Error downloading document: {str(e)}")
        return redirect('home')


# ============= PATIENT AUTHENTICATION =============
@require_http_methods(["GET", "POST"])
def patient_register(request):
    """Patient registration view."""
    if request.method == 'POST':
        # Get form data
        first_name = request.POST.get('first_name')
        last_name = request.POST.get('last_name')
        email = request.POST.get('email')
        password = request.POST.get('password')
        password_confirm = request.POST.get('password_confirm')
        phone = request.POST.get('phone_number')
        
        # Validation
        errors = []
        
        if not first_name or not last_name:
            errors.append("First name and last name are required.")
        
        if not email:
            errors.append("Email is required.")
        elif User.objects.filter(email=email).exists():
            errors.append("An account with this email already exists.")
        
        if not password or len(password) < 8:
            errors.append("Password must be at least 8 characters long.")
        
        if password != password_confirm:
            errors.append("Passwords do not match.")
        
        if errors:
            for error in errors:
                messages.error(request, error)
            return render(request, 'clinic/auth/register.html')
        
        # Create user and patient profile
        try:
            with transaction.atomic():
                user = User.objects.create_user(
                    username=email,
                    email=email,
                    password=password,
                    first_name=first_name,
                    last_name=last_name
                )
                
                # Create patient profile
                PatientProfile.objects.create(
                    user=user,
                    phone_number=phone
                )
                
                messages.success(request, "Account created successfully! Please log in.")
                return redirect('patient_login')
        
        except Exception as e:
            messages.error(request, f"An error occurred: {str(e)}")
            return render(request, 'clinic/auth/register.html')
    
    return render(request, 'clinic/auth/register.html')


@require_http_methods(["GET", "POST"])
def patient_login(request):
    """Patient login view."""
    if request.user.is_authenticated:
        try:
            PatientProfile.objects.get(user=request.user)
            return redirect('patient_dashboard')
        except PatientProfile.DoesNotExist:
            # Logged-in user is not a patient (or profile missing). Clear session and show login.
            logout(request)
            messages.info(request, "Please log in with a patient account.")
    
    if request.method == 'POST':
        email = request.POST.get('email')
        password = request.POST.get('password')
        
        try:
            user = User.objects.get(email=email)
            user = authenticate(request, username=user.username, password=password)
            
            if user is not None:
                login(request, user)
                messages.success(request, f"Welcome back, {user.first_name}!")
                return redirect('patient_dashboard')
            else:
                messages.error(request, "Invalid email or password.")
        except User.DoesNotExist:
            messages.error(request, "Invalid email or password.")
    
    return render(request, 'clinic/auth/login.html')


@login_required(login_url='patient_login')
def patient_logout(request):
    """Patient logout view."""
    logout(request)
    messages.success(request, "You have been logged out successfully.")
    return redirect('home')


# ============= PATIENT PORTAL =============
@login_required(login_url='patient_login')
def patient_dashboard(request):
    """Patient dashboard - main portal view."""
    try:
        patient = PatientProfile.objects.get(user=request.user)
    except PatientProfile.DoesNotExist:
        messages.warning(request, "Patient profile not found. Please contact support.")
        return redirect('home')
    
    # Get upcoming appointments
    upcoming_appointments = patient.appointments.filter(
        appointment_date__gte=timezone.now(),
        status='scheduled'
    ).order_by('appointment_date')[:3]
    
    # Get next appointment
    next_appointment = patient.appointments.filter(
        appointment_date__gte=timezone.now(),
        status='scheduled'
    ).order_by('appointment_date').first()
    
    # Get recent clinical assessments visible to patient
    recent_assessments = patient.clinical_assessments.filter(
        is_visible_to_patient=True
    ).order_by('-created_at')[:5]
    
    # Get pending forms
    pending_forms = patient.consultation_forms.filter(is_signed=False)
    
    # Get session history
    session_history = patient.session_records.all().order_by('-session_date')[:10]
    
    context = {
        'patient': patient,
        'upcoming_appointments': upcoming_appointments,
        'next_appointment': next_appointment,
        'recent_assessments': recent_assessments,
        'pending_forms': pending_forms,
        'session_history': session_history,
    }
    
    return render(request, 'clinic/patient/dashboard.html', context)


@login_required(login_url='patient_login')
def patient_profile(request):
    """Patient profile view and edit."""
    try:
        patient = PatientProfile.objects.get(user=request.user)
    except PatientProfile.DoesNotExist:
        return redirect('patient_dashboard')
    
    if request.method == 'POST':
        # Update patient profile
        patient.phone_number = request.POST.get('phone_number', patient.phone_number)
        patient.date_of_birth = request.POST.get('date_of_birth', patient.date_of_birth)
        patient.gender = request.POST.get('gender', patient.gender)
        patient.address = request.POST.get('address', patient.address)
        patient.emergency_contact = request.POST.get('emergency_contact', patient.emergency_contact)
        patient.emergency_contact_name = request.POST.get('emergency_contact_name', patient.emergency_contact_name)
        
        patient.save()
        messages.success(request, "Profile updated successfully!")
        return redirect('patient_profile')
    
    context = {'patient': patient}
    return render(request, 'clinic/patient/profile.html', context)


@login_required(login_url='patient_login')
def patient_assessments(request):
    """View all clinical assessments."""
    try:
        patient = PatientProfile.objects.get(user=request.user)
    except PatientProfile.DoesNotExist:
        return redirect('patient_dashboard')
    
    assessments = patient.clinical_assessments.filter(
        is_visible_to_patient=True
    ).order_by('-created_at')
    
    context = {
        'patient': patient,
        'assessments': assessments,
    }
    
    return render(request, 'clinic/patient/assessments.html', context)


@login_required(login_url='patient_login')
def assessment_detail(request, assessment_id):
    """View a single assessment."""
    try:
        patient = PatientProfile.objects.get(user=request.user)
        assessment = patient.clinical_assessments.get(
            id=assessment_id,
            is_visible_to_patient=True
        )
    except PatientProfile.DoesNotExist:
        return redirect('patient_dashboard')
    except ClinicalAssessment.DoesNotExist:
        messages.error(request, "Assessment not found.")
        return redirect('patient_assessments')
    
    context = {
        'patient': patient,
        'assessment': assessment,
    }
    
    return render(request, 'clinic/patient/assessment_detail.html', context)


@login_required(login_url='patient_login')
def patient_appointments(request):
    """View patient appointments."""
    try:
        patient = PatientProfile.objects.get(user=request.user)
    except PatientProfile.DoesNotExist:
        return redirect('patient_dashboard')
    
    # Separate upcoming and past appointments
    now = timezone.now()
    upcoming = patient.appointments.filter(
        appointment_date__gte=now
    ).order_by('appointment_date')
    
    past = patient.appointments.filter(
        appointment_date__lt=now
    ).order_by('-appointment_date')
    
    context = {
        'patient': patient,
        'upcoming_appointments': upcoming,
        'past_appointments': past,
    }
    
    return render(request, 'clinic/patient/appointments.html', context)


# ============= API/HELPER VIEWS =============
@login_required
def get_upcoming_sessions(request):
    """API endpoint to get upcoming sessions (used in dashboard)."""
    try:
        patient = PatientProfile.objects.get(user=request.user)
        appointments = patient.appointments.filter(
            appointment_date__gte=timezone.now(),
            status='scheduled'
        ).values('id', 'appointment_date', 'therapist__first_name', 'therapist__last_name')[:5]
        
        return render(request, 'clinic/components/upcoming_sessions.html', {
            'appointments': appointments
        })
    except PatientProfile.DoesNotExist:
        return render(request, 'clinic/components/upcoming_sessions.html', {'appointments': []})


# ============= THERAPIST PORTAL =============
def therapist_login(request):
    """Therapist login view."""
    if request.user.is_authenticated and request.user.is_staff:
        return redirect('therapist_dashboard')
    
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        
        user = authenticate(request, username=username, password=password)
        
        if user is not None and (user.is_staff or user.is_superuser):
            login(request, user)
            messages.success(request, f"Welcome back, {user.first_name}!")
            return redirect('therapist_dashboard')
        else:
            messages.error(request, "Invalid credentials or insufficient permissions.")
    
    return render(request, 'clinic/therapist/login.html')


@login_required(login_url='therapist_login')
def therapist_logout(request):
    """Therapist logout view."""
    if not (request.user.is_staff or request.user.is_superuser):
        return redirect('home')
    
    logout(request)
    messages.success(request, "You have been logged out successfully.")
    return redirect('home')


@login_required(login_url='therapist_login')
def therapist_dashboard(request):
    """Therapist main dashboard."""
    if not (request.user.is_staff or request.user.is_superuser):
        messages.error(request, "Access denied.")
        return redirect('home')
    
    # Get all patients
    all_patients = PatientProfile.objects.all().count()
    
    # Get today's appointments
    today_start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = today_start.replace(hour=23, minute=59, second=59, microsecond=999999)
    today_appointments = Appointment.objects.filter(
        appointment_date__gte=today_start,
        appointment_date__lte=today_end,
        status='scheduled'
    ).order_by('appointment_date')
    
    # Get upcoming appointments
    upcoming_appointments = Appointment.objects.filter(
        appointment_date__gte=timezone.now(),
        status='scheduled'
    ).order_by('appointment_date')[:5]
    
    # Get billing summary
    pending_payments = SessionRecord.objects.filter(
        payment_status__in=['pending', 'partial', 'overdue']
    )
    
    total_pending = sum(session.amount for session in pending_payments)
    
    # Get recent sessions
    recent_sessions = SessionRecord.objects.all().order_by('-session_date')[:10]
    
    context = {
        'all_patients': all_patients,
        'today_appointments': today_appointments,
        'upcoming_appointments': upcoming_appointments,
        'pending_payments': pending_payments,
        'total_pending': total_pending,
        'recent_sessions': recent_sessions,
    }
    
    return render(request, 'clinic/therapist/dashboard.html', context)


@login_required(login_url='therapist_login')
def therapist_patients(request):
    """List all patients for therapist."""
    if not (request.user.is_staff or request.user.is_superuser):
        return redirect('home')
    
    patients = PatientProfile.objects.all().order_by('-created_at')
    
    # Search functionality
    search_query = request.GET.get('search', '')
    if search_query:
        patients = patients.filter(
            user__first_name__icontains=search_query
        ) | patients.filter(
            user__last_name__icontains=search_query
        ) | patients.filter(
            user__email__icontains=search_query
        )
    
    context = {
        'patients': patients,
        'search_query': search_query,
    }
    
    return render(request, 'clinic/therapist/patients.html', context)


@login_required(login_url='therapist_login')
def patient_detail(request, patient_id):
    """View detailed patient information."""
    if not (request.user.is_staff or request.user.is_superuser):
        return redirect('home')
    
    patient = get_object_or_404(PatientProfile, id=patient_id)
    
    # Get patient's appointments
    appointments = patient.appointments.all().order_by('-appointment_date')
    
    # Get patient's assessments
    assessments = patient.clinical_assessments.all().order_by('-created_at')
    
    # Get patient's session records
    sessions = patient.session_records.all().order_by('-session_date')
    
    context = {
        'patient': patient,
        'appointments': appointments,
        'assessments': assessments,
        'sessions': sessions,
    }
    
    return render(request, 'clinic/therapist/patient_detail.html', context)


@login_required(login_url='therapist_login')
def create_assessment(request, patient_id):
    """Create a clinical assessment for a patient."""
    if not (request.user.is_staff or request.user.is_superuser):
        return redirect('home')
    
    patient = get_object_or_404(PatientProfile, id=patient_id)
    
    if request.method == 'POST':
        assessment_type = request.POST.get('assessment_type')
        title = request.POST.get('title')
        content = request.POST.get('content')
        is_visible = request.POST.get('is_visible_to_patient') == 'on'
        
        try:
            assessment = ClinicalAssessment.objects.create(
                patient=patient,
                therapist=request.user,
                assessment_type=assessment_type,
                title=title,
                content=content,
                is_visible_to_patient=is_visible,
                date_shared=timezone.now() if is_visible else None
            )
            messages.success(request, f"Assessment '{title}' created and shared with patient!")
            return redirect('patient_detail', patient_id=patient.id)
        except Exception as e:
            messages.error(request, f"Error creating assessment: {str(e)}")
    
    context = {'patient': patient}
    return render(request, 'clinic/therapist/create_assessment.html', context)


@login_required(login_url='therapist_login')
def manage_appointments(request):
    """Manage all appointments."""
    if not (request.user.is_staff or request.user.is_superuser):
        return redirect('home')
    
    # Get filter from query
    status_filter = request.GET.get('status', 'all')
    
    appointments = Appointment.objects.all().order_by('-appointment_date')
    
    if status_filter != 'all':
        appointments = appointments.filter(status=status_filter)
    
    # Separate upcoming and past
    now = timezone.now()
    upcoming = appointments.filter(appointment_date__gte=now)
    past = appointments.filter(appointment_date__lt=now)
    
    context = {
        'upcoming_appointments': upcoming,
        'past_appointments': past,
        'status_filter': status_filter,
        'appointment_count': appointments.count(),
    }
    
    return render(request, 'clinic/therapist/manage_appointments.html', context)


@login_required(login_url='therapist_login')
def update_appointment_status(request, appointment_id):
    """Update appointment status."""
    if not (request.user.is_staff or request.user.is_superuser):
        return redirect('home')
    
    appointment = get_object_or_404(Appointment, id=appointment_id)
    
    if request.method == 'POST':
        new_status = request.POST.get('status')
        if new_status in ['scheduled', 'completed', 'cancelled', 'no-show']:
            appointment.status = new_status
            appointment.save()
            messages.success(request, f"Appointment status updated to {new_status}.")
    
    return redirect('manage_appointments')


@login_required(login_url='therapist_login')
def billing_dashboard(request):
    """Billing and payment tracking dashboard."""
    if not (request.user.is_staff or request.user.is_superuser):
        return redirect('home')
    
    # Get all sessions
    all_sessions = SessionRecord.objects.all().order_by('-session_date')
    
    # Payment status breakdown
    paid = SessionRecord.objects.filter(payment_status='paid')
    pending = SessionRecord.objects.filter(payment_status='pending')
    partial = SessionRecord.objects.filter(payment_status='partial')
    overdue = SessionRecord.objects.filter(payment_status='overdue')
    
    # Calculate totals
    total_revenue = sum(s.amount for s in paid)
    # Get all non-paid sessions and sum their amounts
    non_paid = SessionRecord.objects.filter(payment_status__in=['pending', 'partial', 'overdue'])
    total_pending = sum(s.amount for s in non_paid)
    
    context = {
        'all_sessions': all_sessions[:20],
        'paid_count': paid.count(),
        'pending_count': pending.count(),
        'partial_count': partial.count(),
        'overdue_count': overdue.count(),
        'total_revenue': total_revenue,
        'total_pending': total_pending,
    }
    
    return render(request, 'clinic/therapist/billing.html', context)


@login_required(login_url='therapist_login')
def update_payment_status(request, session_id):
    """Update payment status for a session."""
    if not (request.user.is_staff or request.user.is_superuser):
        return redirect('home')
    
    session = get_object_or_404(SessionRecord, id=session_id)
    
    if request.method == 'POST':
        payment_status = request.POST.get('payment_status')
        payment_method = request.POST.get('payment_method', '')
        
        if payment_status in ['paid', 'pending', 'partial', 'overdue']:
            session.payment_status = payment_status
            session.payment_method = payment_method
            if payment_status == 'paid':
                session.payment_date = timezone.now()
            session.save()
            messages.success(request, f"Payment status updated to {payment_status}.")
    
    return redirect('billing_dashboard')


# ==================== BOOKING SYSTEM ====================

@login_required(login_url='patient_login')
def booking_calendar(request):
    """Display appointment booking calendar with available therapists."""
    try:
        patient_profile = PatientProfile.objects.get(user=request.user)
    except PatientProfile.DoesNotExist:
        return redirect('patient_register')
    
    # Get all therapists
    therapists = User.objects.filter(is_staff=True, is_superuser=False)
    
    # Get therapist availability (today and next 30 days)
    today = timezone.now().date()
    relevant_appointments = Appointment.objects.filter(
        appointment_date__date__gte=today,
        appointment_date__date__lte=today + timedelta(days=30)
    ).values_list('appointment_date', flat=True)
    
    # Group bookings by therapist
    booking_info = {}
    for therapist in therapists:
        therapist_profile = None
        try:
            therapist_profile = therapist.therapistprofile
        except:
            therapist_profile = None
        
        bookings = Appointment.objects.filter(
            therapist=therapist,
            appointment_date__date__gte=today,
            appointment_date__date__lte=today + timedelta(days=30)
        ).count()
        
        booking_info[therapist.id] = {
            'name': therapist.get_full_name() or therapist.username,
            'profile': therapist_profile,
            'bookings_count': bookings,
            'available': True if bookings < 3 else False  # Max 3 slots per day per therapist
        }
    
    context = {
        'patient_profile': patient_profile,
        'therapists': therapists,
        'booking_info': booking_info,
        'today': today,
        'next_30_days': today + timedelta(days=30),
    }
    
    return render(request, 'clinic/booking_calendar.html', context)


@login_required(login_url='patient_login')
def create_booking(request):
    """Handle appointment booking form submission."""
    try:
        patient_profile = PatientProfile.objects.get(user=request.user)
    except PatientProfile.DoesNotExist:
        return redirect('patient_register')
    
    if request.method == 'POST':
        therapist_id = request.POST.get('therapist_id')
        appointment_date = request.POST.get('appointment_date')
        appointment_time = request.POST.get('appointment_time')
        notes = request.POST.get('notes', '')
        
        try:
            therapist = User.objects.get(id=therapist_id, is_staff=True)
        except User.DoesNotExist:
            messages.error(request, "Selected therapist not found.")
            return redirect('booking_calendar')
        
        # Check for double-booking (therapist can't have overlapping appointments)
        requested_datetime = timezone.datetime.strptime(
            f"{appointment_date} {appointment_time}", "%Y-%m-%d %H:%M"
        )
        requested_datetime = timezone.make_aware(requested_datetime)
        
        # Check if therapist is busy (overlap within 50-minute session window)
        existing_appointment = Appointment.objects.filter(
            therapist=therapist,
            appointment_date__range=[
                requested_datetime - timedelta(minutes=50),
                requested_datetime + timedelta(minutes=50)
            ]
        ).exists()
        
        if existing_appointment:
            messages.error(request, "This time slot is unavailable. Please select another time.")
            return redirect('booking_calendar')
        
        # Create appointment
        with transaction.atomic():
            appointment = Appointment.objects.create(
                patient=patient_profile,
                therapist=therapist,
                appointment_date=requested_datetime,
                duration_minutes=50,
                status='scheduled',
                notes=notes
            )
            
            # Auto-create session record for billing
            SessionRecord.objects.create(
                appointment=appointment,
                session_date=requested_datetime,
                amount=2500,  # Ksh 2,500 per session
                payment_status='pending'
            )
        
        messages.success(request, f"Appointment booked with {therapist.get_full_name()} on {appointment_date}!")
        return redirect('booking_confirmation', appointment_id=appointment.id)
    
    # GET request - show booking form
    therapist_id = request.GET.get('therapist_id')
    if therapist_id:
        try:
            therapist = User.objects.get(id=therapist_id, is_staff=True)
            therapist_profile = getattr(therapist, 'therapistprofile', None)
        except User.DoesNotExist:
            return redirect('booking_calendar')
        
        # Get available time slots for next 7 days
        available_slots = []
        today = timezone.now().date()
        
        for day_offset in range(1, 8):
            current_date = today + timedelta(days=day_offset)
            if current_date.weekday() < 5:  # Weekdays only (Mon-Fri)
                
                # Working hours: 9 AM to 5 PM (50-min slots)
                for hour in range(9, 17):
                    for minute in [0, 30]:
                        slot_datetime = timezone.make_aware(
                            timezone.datetime(current_date.year, current_date.month, current_date.day, hour, minute)
                        )
                        
                        # Check if slot is free
                        is_booked = Appointment.objects.filter(
                            therapist=therapist,
                            appointment_date__range=[
                                slot_datetime - timedelta(minutes=25),
                                slot_datetime + timedelta(minutes=59)
                            ]
                        ).exists()
                        
                        if not is_booked and slot_datetime > timezone.now():
                            available_slots.append({
                                'date': current_date,
                                'time': f"{hour:02d}:{minute:02d}",
                                'datetime': slot_datetime,
                                'display': f"{current_date.strftime('%A, %b %d')} at {hour:02d}:{minute:02d}"
                            })
        
        context = {
            'therapist': therapist,
            'therapist_profile': therapist_profile,
            'patient_profile': patient_profile,
            'available_slots': available_slots,
        }
        
        return render(request, 'clinic/booking_form.html', context)
    
    return redirect('booking_calendar')


@login_required(login_url='patient_login')
def booking_confirmation(request, appointment_id):
    """Show booking confirmation page."""
    try:
        patient_profile = PatientProfile.objects.get(user=request.user)
    except PatientProfile.DoesNotExist:
        return redirect('patient_register')
    
    appointment = get_object_or_404(
        Appointment, 
        id=appointment_id, 
        patient=patient_profile
    )
    
    context = {
        'appointment': appointment,
        'patient_profile': patient_profile,
    }
    
    return render(request, 'clinic/booking_confirmation.html', context)


@login_required(login_url='patient_login')
def cancel_booking(request, appointment_id):
    """Cancel a scheduled appointment."""
    try:
        patient_profile = PatientProfile.objects.get(user=request.user)
    except PatientProfile.DoesNotExist:
        return redirect('patient_register')
    
    appointment = get_object_or_404(
        Appointment,
        id=appointment_id,
        patient=patient_profile,
        status='scheduled'
    )
    
    if request.method == 'POST':
        # Allow cancellation only if appointment is in the future
        if appointment.appointment_date > timezone.now():
            appointment.status = 'cancelled'
            appointment.save()
            messages.success(request, "Appointment cancelled successfully.")
            return redirect('patient_appointments')
        else:
            messages.error(request, "Cannot cancel past appointments.")
            return redirect('patient_appointments')
    
    # GET - show confirmation page
    context = {
        'appointment': appointment,
        'patient_profile': patient_profile,
    }
    
    return render(request, 'clinic/booking_cancel_confirm.html', context)


@login_required
def check_availability(request):
    """API endpoint to check therapist availability (returns JSON)."""
    from django.http import JsonResponse
    
    therapist_id = request.GET.get('therapist_id')
    date_str = request.GET.get('date')  # YYYY-MM-DD format
    
    if not therapist_id or not date_str:
        return JsonResponse({'error': 'Missing parameters'}, status=400)
    
    try:
        therapist = User.objects.get(id=therapist_id, is_staff=True)
    except User.DoesNotExist:
        return JsonResponse({'error': 'Therapist not found'}, status=404)
    
    try:
        target_date = timezone.datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        return JsonResponse({'error': 'Invalid date format'}, status=400)
    
    # Get all booked slots for this therapist on this date
    booked_times = Appointment.objects.filter(
        therapist=therapist,
        appointment_date__date=target_date
    ).values_list('appointment_date__time', flat=True)
    
    # Generate available slots (9 AM to 5 PM, 30-min intervals)
    available_slots = []
    for hour in range(9, 17):
        for minute in [0, 30]:
            slot_time = f"{hour:02d}:{minute:02d}"
            # Check rough availability (not perfectly booked)
            if not any(booked_time.strftime("%H:%M") == slot_time for booked_time in booked_times):
                available_slots.append(slot_time)
    
    return JsonResponse({
        'date': date_str,
        'therapist': therapist.get_full_name(),
        'available_slots': available_slots,
        'booked_count': len(booked_times),
    })

