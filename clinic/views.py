from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User, AbstractUser
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.contrib import messages
from django.db import transaction, models
from django.http import FileResponse, HttpResponse, JsonResponse
from .models import (
    PatientProfile,
    ClinicalAssessment,
    Appointment,
    SessionRecord,
    Document,
    FeedbackQuestion,
    FeedbackSubmission,
    FeedbackAnswer,
    PaymentTransaction,
)
from django.utils import timezone
from datetime import timedelta, date
from typing import TYPE_CHECKING
import mimetypes
import json
import calendar

from .mpesa import load_mpesa_config, get_access_token, stk_push

if TYPE_CHECKING:
    from django.db.models import QuerySet


def _in_group(user: User, group_name: str) -> bool:
    return user.is_authenticated and user.groups.filter(name=group_name).exists()


def _staff_has_any_group(user: AbstractUser, group_names: list[str]) -> bool:
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    if not user.is_staff:
        return False
    return user.groups.filter(name__in=group_names).exists() or user.groups.count() == 0


def _require_staff_groups(request, group_names: list[str]) -> bool:
    if _staff_has_any_group(request.user, group_names):
        return True
    messages.error(request, "Access denied.")
    return False

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

    pending_feedback_sessions = patient.session_records.filter(feedback_submission__isnull=True).order_by("-session_date")[:3]
    pending_payment_sessions = patient.session_records.filter(payment_status__in=["pending", "partial", "overdue"]).order_by(
        "-session_date"
    )[:3]
    
    context = {
        'patient': patient,
        'upcoming_appointments': upcoming_appointments,
        'next_appointment': next_appointment,
        'recent_assessments': recent_assessments,
        'pending_forms': pending_forms,
        'session_history': session_history,
        'pending_feedback_sessions': pending_feedback_sessions,
        'pending_payment_sessions': pending_payment_sessions,
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


# ============= FEEDBACK & PAYMENTS (PATIENT) =============
@login_required(login_url="patient_login")
@require_http_methods(["GET", "POST"])
def patient_feedback(request, session_id: int):
    """Guided feedback form for a completed session (or any session, if enabled)."""
    try:
        patient = PatientProfile.objects.get(user=request.user)
    except PatientProfile.DoesNotExist:
        return redirect("patient_dashboard")

    session = get_object_or_404(SessionRecord, id=session_id, patient=patient)
    existing = getattr(session, "feedback_submission", None)
    questions = list(FeedbackQuestion.objects.filter(is_active=True))

    if request.method == "POST":
        if existing:
            messages.info(request, "Feedback already submitted for this session.")
            return redirect("patient_dashboard")

        comment = request.POST.get("comment", "").strip()
        answers: list[tuple[FeedbackQuestion, int]] = []

        for question in questions:
            raw = request.POST.get(f"q_{question.id}", "").strip()
            try:
                rating = int(raw)
            except ValueError:
                rating = 0
            if rating < 1 or rating > 5:
                messages.error(request, "Please answer all guided questions (1-5).")
                return render(
                    request,
                    "clinic/patient/feedback.html",
                    {"patient": patient, "session": session, "questions": questions, "existing": existing},
                )
            answers.append((question, rating))

        with transaction.atomic():
            submission = FeedbackSubmission.objects.create(
                patient=patient, session_record=session, appointment=session.appointment, comment=comment
            )
            FeedbackAnswer.objects.bulk_create(
                [FeedbackAnswer(submission=submission, question=q, rating_1_5=r) for (q, r) in answers]
            )

        messages.success(request, "Thank you! Your feedback has been submitted.")
        return redirect("patient_dashboard")

    return render(
        request,
        "clinic/patient/feedback.html",
        {"patient": patient, "session": session, "questions": questions, "existing": existing},
    )


@login_required(login_url="patient_login")
def patient_payments(request):
    """List pending payments for a patient."""
    try:
        patient = PatientProfile.objects.get(user=request.user)
    except PatientProfile.DoesNotExist:
        return redirect("patient_dashboard")

    pending_sessions = patient.session_records.filter(payment_status__in=["pending", "partial", "overdue"]).select_related(
        "appointment"
    )
    return render(
        request,
        "clinic/patient/payments.html",
        {"patient": patient, "pending_sessions": pending_sessions},
    )


# ============= M-PESA (PATIENT + RECEPTION) =============
@login_required
@require_http_methods(["GET", "POST"])
def mpesa_pay_session(request, session_id: int):
    """Start an STK push for a specific session (patient or receptionist)."""
    session = get_object_or_404(SessionRecord, id=session_id)

    # Authorization: patient can pay their own sessions; receptionist can pay any.
    is_reception = _staff_has_any_group(request.user, ["receptionist"])
    if not is_reception:
        try:
            patient = PatientProfile.objects.get(user=request.user)
        except PatientProfile.DoesNotExist:
            messages.error(request, "Access denied.")
            return redirect("home")
        if session.patient_id != patient.id:
            messages.error(request, "Access denied.")
            return redirect("patient_dashboard")

    config = load_mpesa_config()
    recent = session.payment_transactions.all()[:10]

    if request.method == "POST":
        phone_number = (request.POST.get("phone_number") or "").strip()
        if not phone_number and hasattr(session.patient, "phone_number"):
            phone_number = session.patient.phone_number

        try:
            amount_int = int(session.amount)
        except Exception:
            amount_int = 0

        if amount_int <= 0:
            messages.error(request, "Invalid amount for this session.")
            return redirect("patient_payments" if not is_reception else "reception_dashboard")

        tx = PaymentTransaction.objects.create(
            session_record=session,
            created_by=request.user,
            phone_number=phone_number,
            amount=session.amount,
            currency=session.currency,
            status=PaymentTransaction.STATUS_INITIATED,
            account_reference=f"SESSION-{session.id}",
            description="Therapy session payment",
        )

        if not config.is_configured:
            tx.status = PaymentTransaction.STATUS_FAILED
            tx.result_desc = "M-PESA not configured"
            tx.save(update_fields=["status", "result_desc", "updated_at"])
            messages.error(request, "M-PESA is not configured on this server yet. Add MPESA_* env vars and try again.")
            return redirect("patient_payments" if not is_reception else "reception_dashboard")

        try:
            token = get_access_token(config)
            resp = stk_push(
                config=config,
                token=token,
                phone_number=phone_number,
                amount=amount_int,
                account_reference=tx.account_reference or f"SESSION-{session.id}",
                transaction_desc=tx.description or "KEWOTA Payment",
            )
            tx.callback_payload = {"stk_push_response": resp}
            tx.merchant_request_id = resp.get("MerchantRequestID", "") or resp.get("MerchantRequestId", "")
            tx.checkout_request_id = resp.get("CheckoutRequestID", "") or resp.get("CheckoutRequestId", "")

            if resp.get("ResponseCode") == "0":
                tx.status = PaymentTransaction.STATUS_PENDING
                tx.result_desc = resp.get("ResponseDescription", "Pending")
                messages.success(request, "Payment prompt sent to phone. Complete it on your handset.")
            else:
                tx.status = PaymentTransaction.STATUS_FAILED
                tx.result_desc = resp.get("ResponseDescription", "Failed to initiate")
                messages.error(request, f"M-PESA initiation failed: {tx.result_desc}")

            tx.save()
            return redirect("mpesa_pay_session", session_id=session.id)
        except Exception as e:
            tx.status = PaymentTransaction.STATUS_FAILED
            tx.result_desc = str(e)[:255]
            tx.save(update_fields=["status", "result_desc", "updated_at"])
            messages.error(request, f"Could not initiate M-PESA payment: {str(e)}")

    return render(
        request,
        "clinic/payments/mpesa_pay.html",
        {"session": session, "transactions": recent, "is_reception": is_reception},
    )


@csrf_exempt
@require_http_methods(["POST"])
def mpesa_callback(request):
    """Daraja STK push callback endpoint."""
    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except Exception:
        payload = {}

    stk = (
        payload.get("Body", {})
        .get("stkCallback", {})
    )
    checkout = stk.get("CheckoutRequestID") or stk.get("CheckoutRequestId") or ""
    result_code = stk.get("ResultCode")
    result_desc = stk.get("ResultDesc", "")

    tx = PaymentTransaction.objects.filter(checkout_request_id=checkout).order_by("-initiated_at").first()
    if not tx:
        return JsonResponse({"ResultCode": 0, "ResultDesc": "Accepted"})

    tx.callback_payload = payload
    tx.result_code = result_code
    tx.result_desc = (result_desc or "")[:255]

    if result_code == 0:
        receipt = ""
        items = stk.get("CallbackMetadata", {}).get("Item", []) or []
        for item in items:
            if item.get("Name") == "MpesaReceiptNumber":
                receipt = str(item.get("Value") or "")
                break
        tx.mpesa_receipt_number = receipt
        tx.status = PaymentTransaction.STATUS_SUCCESS

        session = tx.session_record
        session.payment_status = "paid"
        session.payment_method = "M-PESA"
        session.payment_date = timezone.now()
        session.save(update_fields=["payment_status", "payment_method", "payment_date", "updated_at"])
    else:
        tx.status = PaymentTransaction.STATUS_FAILED if result_code != 1032 else PaymentTransaction.STATUS_CANCELED

    tx.save()
    return JsonResponse({"ResultCode": 0, "ResultDesc": "Accepted"})


@login_required(login_url="reception_login")
@require_http_methods(["POST"])
def mpesa_manual_confirm(request, session_id: int):
    """Receptionist marks a session as paid after an over-the-counter paybill/till payment."""
    if not _require_staff_groups(request, ["receptionist"]):
        return redirect("home")

    session = get_object_or_404(SessionRecord, id=session_id)
    receipt = (request.POST.get("mpesa_receipt_number") or "").strip()

    with transaction.atomic():
        PaymentTransaction.objects.create(
            session_record=session,
            created_by=request.user,
            phone_number=request.POST.get("phone_number", "").strip(),
            amount=session.amount,
            currency=session.currency,
            status=PaymentTransaction.STATUS_SUCCESS,
            mpesa_receipt_number=receipt,
            result_code=0,
            result_desc="Manual confirmation",
            callback_payload={"manual": True},
        )
        session.payment_status = "paid"
        session.payment_method = "M-PESA"
        session.payment_date = timezone.now()
        session.save(update_fields=["payment_status", "payment_method", "payment_date", "updated_at"])

    messages.success(request, "Payment marked as paid.")
    return redirect("reception_dashboard")


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


@login_required
@require_http_methods(["GET"])
def get_available_slots(request):
    """API endpoint to get available time slots for a given date and therapist."""
    therapist_id = request.GET.get('therapist_id')
    date_str = request.GET.get('date')  # Format: YYYY-MM-DD
    
    if not therapist_id or not date_str:
        return JsonResponse({'error': 'Missing therapist_id or date'}, status=400)
    
    try:
        therapist = User.objects.get(id=therapist_id, is_staff=True)
    except User.DoesNotExist:
        return JsonResponse({'error': 'Therapist not found'}, status=404)
    
    try:
        requested_date = timezone.datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        return JsonResponse({'error': 'Invalid date format'}, status=400)
    
    # Check if date is in the past or more than 30 days away
    today = timezone.now().date()
    if requested_date < today or (requested_date - today).days > 30:
        return JsonResponse({'error': 'Invalid date range'}, status=400)
    
    # Check if it's a weekday (Monday-Saturday, no Sunday)
    if requested_date.weekday() >= 6:  # Sunday=6
        return JsonResponse({'slots': [], 'fully_booked': True, 'message': 'No availability on Sundays'}, status=200)
    
    # Generate 1-hour slots from 7 AM to 6 PM (11 slots max)
    slots = []
    is_today = requested_date == today
    now = timezone.now()#garvine olwal made this
    
    for hour in range(7, 18):  # 7 AM to 5 PM (so last slot ends at 6 PM)
        slot_datetime = timezone.make_aware(
            timezone.datetime(requested_date.year, requested_date.month, requested_date.day, hour, 0)
        )
        
        # For today only: skip slots that have already started
        # For future dates: show all slots
        if is_today and slot_datetime <= now:
            continue
        
        # Check if this time slot is already booked (1-hour duration)
        is_booked = Appointment.objects.filter(
            therapist=therapist,
            appointment_date__gte=slot_datetime,
            appointment_date__lt=slot_datetime + timedelta(hours=1),
            status__in=['scheduled', 'completed']
        ).exists()
        
        slots.append({
            'time': f"{hour:02d}:00",
            'datetime': slot_datetime.isoformat(),
            'available': not is_booked,
        })
    
    # Check if all slots are booked
    fully_booked = all(not slot['available'] for slot in slots) and len(slots) > 0
    
    return JsonResponse({
        'slots': slots,
        'fully_booked': fully_booked,
        'therapist_id': therapist_id,
        'date': date_str,
    })


# ============= RECEPTION / CUSTOMER CARE DESK =============
def reception_login(request):
    """Receptionist (customer care) login view."""
    if request.user.is_authenticated and _staff_has_any_group(request.user, ["receptionist"]):
        return redirect("reception_dashboard")

    if request.method == "POST":
        username = request.POST.get("username")
        password = request.POST.get("password")

        user = authenticate(request, username=username, password=password)
        if user is not None and _staff_has_any_group(user, ["receptionist"]):
            login(request, user)
            messages.success(request, f"Welcome back, {user.first_name}!")
            return redirect("reception_dashboard")
        messages.error(request, "Invalid credentials or insufficient permissions.")

    return render(request, "clinic/reception/login.html")


@login_required(login_url="reception_login")
def reception_logout(request):
    if not _staff_has_any_group(request.user, ["receptionist"]):
        return redirect("home")
    logout(request)
    messages.success(request, "You have been logged out successfully.")
    return redirect("home")


@login_required(login_url="reception_login")
def reception_dashboard(request):
    if not _require_staff_groups(request, ["receptionist"]):
        return redirect("home")

    now = timezone.now()
    upcoming_appointments = Appointment.objects.filter(appointment_date__gte=now, status="scheduled").order_by(
        "appointment_date"
    )[:20]
    pending_sessions = SessionRecord.objects.filter(payment_status__in=["pending", "partial", "overdue"]).select_related(
        "patient",
        "appointment",
    )[:30]
    return render(
        request,
        "clinic/reception/dashboard.html",
        {"upcoming_appointments": upcoming_appointments, "pending_sessions": pending_sessions},
    )


@login_required(login_url="reception_login")
def reception_patients(request):
    if not _require_staff_groups(request, ["receptionist"]):
        return redirect("home")

    search_query = (request.GET.get("search") or "").strip()
    patients = PatientProfile.objects.select_related("user").all().order_by("-created_at")
    if search_query:
        patients = patients.filter(
            models.Q(user__first_name__icontains=search_query)
            | models.Q(user__last_name__icontains=search_query)
            | models.Q(user__email__icontains=search_query)
            | models.Q(phone_number__icontains=search_query)
        )

    return render(request, "clinic/reception/patients.html", {"patients": patients[:200], "search_query": search_query})


@login_required(login_url="reception_login")
@require_http_methods(["GET", "POST"])
def reception_create_patient(request):
    if not _require_staff_groups(request, ["receptionist"]):
        return redirect("home")

    if request.method == "POST":
        first_name = (request.POST.get("first_name") or "").strip()
        last_name = (request.POST.get("last_name") or "").strip()
        email = (request.POST.get("email") or "").strip().lower()
        phone = (request.POST.get("phone_number") or "").strip()
        password = (request.POST.get("password") or "").strip()

        errors: list[str] = []
        if not first_name or not last_name:
            errors.append("First and last name are required.")
        if not email:
            errors.append("Email is required.")
        elif User.objects.filter(email=email).exists():
            errors.append("An account with this email already exists.")
        if not password or len(password) < 8:
            errors.append("Password must be at least 8 characters.")

        if errors:
            for e in errors:
                messages.error(request, e)
            return render(request, "clinic/reception/create_patient.html")

        with transaction.atomic():
            user = User.objects.create_user(
                username=email,
                email=email,
                password=password,
                first_name=first_name,
                last_name=last_name,
            )
            patient = PatientProfile.objects.create(user=user, phone_number=phone)

        messages.success(request, "Client account created.")
        return redirect("reception_patient_detail", patient_id=patient.id)

    return render(request, "clinic/reception/create_patient.html")


@login_required(login_url="reception_login")
def reception_patient_detail(request, patient_id: int):
    if not _require_staff_groups(request, ["receptionist"]):
        return redirect("home")

    patient = get_object_or_404(PatientProfile.objects.select_related("user"), id=patient_id)
    appointments = patient.appointments.all().order_by("-appointment_date")[:50]
    sessions = patient.session_records.select_related("appointment").all().order_by("-session_date")[:50]
    return render(
        request,
        "clinic/reception/patient_detail.html",
        {"patient": patient, "appointments": appointments, "sessions": sessions},
    )


@login_required(login_url="reception_login")
@require_http_methods(["GET", "POST"])
def reception_book_appointment(request, patient_id: int):
    if not _require_staff_groups(request, ["receptionist"]):
        return redirect("home")

    patient = get_object_or_404(PatientProfile.objects.select_related("user"), id=patient_id)
    therapists = User.objects.filter(is_staff=True)

    if request.method == "POST":
        therapist_id = request.POST.get("therapist_id")
        appointment_date = request.POST.get("appointment_date")
        appointment_time = request.POST.get("appointment_time")
        notes = request.POST.get("notes", "")

        try:
            therapist = User.objects.get(id=therapist_id, is_staff=True)
        except User.DoesNotExist:
            messages.error(request, "Selected clinician not found.")
            return redirect("reception_book_appointment", patient_id=patient.id)

        try:
            requested_datetime = timezone.datetime.strptime(f"{appointment_date} {appointment_time}", "%Y-%m-%d %H:%M")
            requested_datetime = timezone.make_aware(requested_datetime)
        except Exception:
            messages.error(request, "Invalid date/time.")
            return redirect("reception_book_appointment", patient_id=patient.id)

        existing = Appointment.objects.filter(
            therapist=therapist,
            appointment_date__range=[requested_datetime - timedelta(minutes=50), requested_datetime + timedelta(minutes=50)],
        ).exists()
        if existing:
            messages.error(request, "This time slot is unavailable for the selected clinician.")
            return redirect("reception_book_appointment", patient_id=patient.id)

        with transaction.atomic():
            appointment = Appointment.objects.create(
                patient=patient,
                therapist=therapist,
                appointment_date=requested_datetime,
                duration_minutes=50,
                status="scheduled",
                notes=notes,
            )
            SessionRecord.objects.create(
                patient=patient,
                appointment=appointment,
                therapist=therapist,
                session_date=requested_datetime,
                amount=2500,
                payment_status="pending",
            )

        messages.success(request, "Appointment created.")
        return redirect("reception_patient_detail", patient_id=patient.id)

    return render(
        request,
        "clinic/reception/book_appointment.html",
        {"patient": patient, "therapists": therapists},
    )


@login_required(login_url="reception_login")
@require_http_methods(["POST"])
def reception_update_appointment_status(request, appointment_id: int):
    if not _require_staff_groups(request, ["receptionist"]):
        return redirect("home")

    appointment = get_object_or_404(Appointment, id=appointment_id)
    new_status = request.POST.get("status")
    if new_status in ["scheduled", "completed", "cancelled", "no-show"]:
        appointment.status = new_status
        appointment.save(update_fields=["status", "updated_at"])
        messages.success(request, "Appointment status updated.")
    return redirect("reception_patient_detail", patient_id=appointment.patient_id)


# ============= THERAPIST PORTAL =============
def therapist_login(request):
    """Therapist login view."""
    if request.user.is_authenticated and _staff_has_any_group(request.user, ["therapist", "doctor"]):
        return redirect('therapist_dashboard')
    
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        
        user = authenticate(request, username=username, password=password)
        
        if user is not None and _staff_has_any_group(user, ["therapist", "doctor"]):
            login(request, user)
            messages.success(request, f"Welcome back, {user.first_name}!")
            return redirect('therapist_dashboard')
        else:
            messages.error(request, "Invalid credentials or insufficient permissions.")
    
    return render(request, 'clinic/therapist/login.html')


@login_required(login_url='therapist_login')
def therapist_logout(request):
    """Therapist logout view."""
    if not _staff_has_any_group(request.user, ["therapist", "doctor"]):
        return redirect('home')
    
    logout(request)
    messages.success(request, "You have been logged out successfully.")
    return redirect('home')


@login_required(login_url='therapist_login')
def therapist_dashboard(request):
    """Therapist main dashboard."""
    if not _require_staff_groups(request, ["therapist", "doctor"]):
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
    if not _require_staff_groups(request, ["therapist", "doctor"]):
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
    if not _require_staff_groups(request, ["therapist", "doctor"]):
        return redirect('home')
    
    patient = get_object_or_404(PatientProfile, id=patient_id)
    
    # Get patient's appointments
    appointments = patient.appointments.all().order_by('-appointment_date')
    
    # Get patient's assessments
    assessments = patient.clinical_assessments.all().order_by('-created_at')
    
    # Get patient's session records
    sessions = patient.session_records.all().order_by('-session_date')

    feedback = patient.feedback_submissions.all().select_related("session_record").order_by("-submitted_at")[:20]
    
    context = {
        'patient': patient,
        'appointments': appointments,
        'assessments': assessments,
        'sessions': sessions,
        'feedback': feedback,
    }
    
    return render(request, 'clinic/therapist/patient_detail.html', context)


@login_required(login_url='therapist_login')
def create_assessment(request, patient_id):
    """Create a clinical assessment for a patient."""
    if not _require_staff_groups(request, ["therapist", "doctor"]):
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
    if not _require_staff_groups(request, ["therapist", "doctor"]):
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
    if not _require_staff_groups(request, ["therapist", "doctor"]):
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
    if not _require_staff_groups(request, ["therapist", "doctor"]):
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
    if not _require_staff_groups(request, ["therapist", "doctor"]):
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
    
    # Generate calendar data with appointment markers
    current_month = today.replace(day=1)
    month_cal = calendar.monthcalendar(current_month.year, current_month.month)
    
    # Get all appointments for this month
    month_start = current_month.replace(day=1)
    month_end = (month_start + timedelta(days=32)).replace(day=1) - timedelta(days=1)
    
    appointments_this_month = Appointment.objects.filter(
        appointment_date__date__gte=month_start,
        appointment_date__date__lte=month_end,
        status='scheduled'
    ).values_list('appointment_date__date', flat=True)
    
    scheduled_dates = set([d.day for d in appointments_this_month])
    
    # Build calendar with date info
    calendar_data = []
    for week in month_cal:
        week_data = []
        for day in week:
            if day == 0:
                week_data.append({'day': None, 'is_scheduled': False})
            else:
                is_scheduled = day in scheduled_dates
                week_data.append({
                    'day': day,
                    'is_scheduled': is_scheduled,
                    'date_obj': date(current_month.year, current_month.month, day)
                })
        calendar_data.append(week_data)
    
    context = {
        'patient_profile': patient_profile,
        'therapists': therapists,
        'booking_info': booking_info,
        'today': today,
        'next_30_days': today + timedelta(days=30),
        'current_month': current_month,
        'calendar_data': calendar_data,
        'month_name': current_month.strftime('%B %Y'),
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
        
        # Validate date and time format
        try:
            requested_datetime = timezone.datetime.strptime(
                f"{appointment_date} {appointment_time}", "%Y-%m-%d %H:%M"
            )
            requested_datetime = timezone.make_aware(requested_datetime)
        except ValueError:
            messages.error(request, "Invalid date or time format.")
            return redirect('booking_calendar')
        
        # Validate date is not in past and not more than 30 days away
        today = timezone.now().date()
        requested_date = requested_datetime.date()
        if requested_date < today or (requested_date - today).days > 30:
            messages.error(request, "Booking date must be within the next 30 days.")
            return redirect('booking_calendar')
        
        # Check if it's a weekday
        if requested_date.weekday() >= 5:
            messages.error(request, "Bookings are only available Monday to Friday.")
            return redirect('booking_calendar')
        
        # Validate time is within 7 AM to 6 PM range
        hour = requested_datetime.hour
        if hour < 7 or hour >= 18:
            messages.error(request, "Sessions are only available from 7 AM to 5 PM.")
            return redirect('booking_calendar')
        
        # Check if therapist is busy (1-hour duration)
        existing_appointment = Appointment.objects.filter(
            therapist=therapist,
            appointment_date__gte=requested_datetime,
            appointment_date__lt=requested_datetime + timedelta(hours=1),
            status__in=['scheduled', 'completed']
        ).exists()
        
        if existing_appointment:
            messages.error(request, "This time slot is unavailable. Please select another time.")
            return redirect('booking_calendar')
        
        # Create appointment with 1-hour duration
        with transaction.atomic():
            appointment = Appointment.objects.create(
                patient=patient_profile,
                therapist=therapist,
                appointment_date=requested_datetime,
                duration_minutes=60,  # 1-hour sessions
                status='scheduled',
                notes=notes
            )
            
            # Auto-create session record for billing
            SessionRecord.objects.create(
                patient=patient_profile,
                appointment=appointment,
                session_date=requested_datetime,
                therapist=therapist,
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
        
        try:
            patient_profile = PatientProfile.objects.get(user=request.user)
        except PatientProfile.DoesNotExist:
            return redirect('patient_register')
        
        context = {
            'therapist': therapist,
            'therapist_profile': therapist_profile,
            'patient_profile': patient_profile,
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

    session_record = getattr(appointment, "session_record", None)
    
    context = {
        'appointment': appointment,
        'patient_profile': patient_profile,
        'session_record': session_record,
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

