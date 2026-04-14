from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone

# ============= PATIENT PROFILE =============
class PatientProfile(models.Model):
    """Extended user profile with patient-specific information."""
    
    GENDER_CHOICES = [
        ('M', 'Male'),
        ('F', 'Female'),
        ('O', 'Other'),
        ('P', 'Prefer not to say'),
    ]
    
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='patient_profile')
    phone_number = models.CharField(max_length=15, blank=True)
    date_of_birth = models.DateField(null=True, blank=True)
    gender = models.CharField(max_length=1, choices=GENDER_CHOICES, blank=True)
    address = models.TextField(blank=True)
    emergency_contact = models.CharField(max_length=15, blank=True)
    emergency_contact_name = models.CharField(max_length=100, blank=True)
    
    # Medical History
    medical_history = models.TextField(blank=True, help_text="Previous medical or psychiatric conditions")
    current_medications = models.TextField(blank=True)
    allergies = models.TextField(blank=True)
    
    # Consent & Forms
    consent_form_signed = models.BooleanField(default=False)
    consent_form_date = models.DateTimeField(null=True, blank=True)
    biodata_complete = models.BooleanField(default=False)
    
    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"{self.user.get_full_name()} - Patient"
    
    class Meta:
        ordering = ['-created_at']


# ============= CONSULTATION FORM =============
class ConsultationForm(models.Model):
    """Digital storage of patient consultation forms (Biodata, Consent, Contract)."""
    
    FORM_TYPE_CHOICES = [
        ('consent', 'Consent Form'),
        ('biodata', 'Client Biodata'),
        ('contract', 'Service Contract'),
    ]
    
    patient = models.ForeignKey(PatientProfile, on_delete=models.CASCADE, related_name='consultation_forms')
    form_type = models.CharField(max_length=20, choices=FORM_TYPE_CHOICES)
    form_data = models.JSONField(default=dict, blank=True)  # Store form responses as JSON
    is_signed = models.BooleanField(default=False)
    signed_date = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"{self.patient.user.get_full_name()} - {self.get_form_type_display()}"
    
    class Meta:
        unique_together = ('patient', 'form_type')
        ordering = ['-created_at']


# ============= APPOINTMENT =============
class Appointment(models.Model):
    """Digital appointment booking system."""
    
    STATUS_CHOICES = [
        ('scheduled', 'Scheduled'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
        ('no-show', 'No Show'),
    ]
    
    patient = models.ForeignKey(PatientProfile, on_delete=models.CASCADE, related_name='appointments')
    therapist = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, 
                                  related_name='patient_appointments')
    appointment_date = models.DateTimeField()
    duration_minutes = models.IntegerField(default=50)  # 50-minute session
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='scheduled')
    notes = models.TextField(blank=True)
    cancellation_reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"{self.patient.user.get_full_name()} - {self.appointment_date.strftime('%Y-%m-%d %H:%M')}"
    
    class Meta:
        ordering = ['-appointment_date']
        unique_together = ('patient', 'appointment_date')  # Prevent double bookings


# ============= SESSION RECORD & BILLING =============
class SessionRecord(models.Model):
    """Tracks completed sessions and billing information."""
    
    PAYMENT_STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('paid', 'Paid'),
        ('partial', 'Partial'),
        ('overdue', 'Overdue'),
    ]
    
    patient = models.ForeignKey(PatientProfile, on_delete=models.CASCADE, related_name='session_records')
    appointment = models.OneToOneField(Appointment, on_delete=models.CASCADE, related_name='session_record')
    session_date = models.DateTimeField(auto_now_add=True)
    therapist = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, 
                                  related_name='conducted_sessions')
    
    # Billing
    amount = models.DecimalField(max_digits=10, decimal_places=2, default=2500.00)  # Ksh 2,500 default
    currency = models.CharField(max_length=3, default='KES')
    payment_status = models.CharField(max_length=20, choices=PAYMENT_STATUS_CHOICES, default='pending')
    payment_date = models.DateTimeField(null=True, blank=True)
    payment_method = models.CharField(max_length=50, blank=True)
    
    # Session Notes (internal)
    session_notes = models.TextField(blank=True, help_text="Internal notes for therapist")
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"{self.patient.user.get_full_name()} - Session {self.session_date.strftime('%Y-%m-%d')}"
    
    class Meta:
        ordering = ['-session_date']


# ============= CLINICAL ASSESSMENT =============
class ClinicalAssessment(models.Model):
    """Session feedback and clinical assessment uploaded by therapist."""
    
    ASSESSMENT_TYPE_CHOICES = [
        ('feedback', 'Session Feedback'),
        ('assessment', 'Clinical Assessment'),
        ('progress_report', 'Progress Report'),
        ('treatment_plan', 'Treatment Plan'),
    ]
    
    patient = models.ForeignKey(PatientProfile, on_delete=models.CASCADE, related_name='clinical_assessments')
    session_record = models.OneToOneField(SessionRecord, on_delete=models.CASCADE, 
                                          related_name='clinical_assessment', null=True, blank=True)
    therapist = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    
    assessment_type = models.CharField(max_length=20, choices=ASSESSMENT_TYPE_CHOICES)
    title = models.CharField(max_length=200)
    content = models.TextField()  # The actual assessment/feedback
    
    # Visibility
    is_visible_to_patient = models.BooleanField(default=True)
    date_shared = models.DateTimeField(null=True, blank=True)
    
    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"{self.patient.user.get_full_name()} - {self.get_assessment_type_display()}: {self.title}"
    
    class Meta:
        ordering = ['-created_at']
        verbose_name_plural = "Clinical Assessments"


# ============= THERAPIST PROFILE =============
class TherapistProfile(models.Model):
    """Profile for therapists/admin staff."""
    
    SPECIALIZATION_CHOICES = [
        ('trauma', 'Trauma & PTSD'),
        ('individual', 'Individual Therapy'),
        ('family', 'Family Counseling'),
        ('general', 'General Practice'),
    ]
    
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='therapist_profile')
    license_number = models.CharField(max_length=100, unique=True)
    specialization = models.CharField(max_length=20, choices=SPECIALIZATION_CHOICES)
    bio = models.TextField(blank=True)
    phone_number = models.CharField(max_length=15, blank=True)
    
    # Practice Info
    hourly_rate = models.DecimalField(max_digits=10, decimal_places=2, default=2500.00)
    session_duration = models.IntegerField(default=50, help_text="Session duration in minutes")
    
    # Availability
    is_available = models.BooleanField(default=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"Dr. {self.user.get_full_name()} - {self.get_specialization_display()}"
    
    class Meta:
        ordering = ['user__first_name']


# ============= DOWNLOADABLE DOCUMENTS =============
class Document(models.Model):
    """Downloadable documents for patients (Consent Form, Biodata, Contract)."""
    
    DOCUMENT_TYPE_CHOICES = [
        ('consent', 'Informed Consent Form'),
        ('biodata', 'Client Biodata Form'),
        ('contract', 'Service Contract'),
    ]
    
    document_type = models.CharField(
        max_length=20, 
        choices=DOCUMENT_TYPE_CHOICES,
        unique=True,
        help_text="Type of document"
    )
    title = models.CharField(max_length=200, help_text="Document title shown on website")
    description = models.TextField(blank=True, help_text="Brief description of what the document contains")
    file = models.FileField(upload_to='documents/', help_text="Upload PDF file")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"{self.get_document_type_display()}"
    
    class Meta:
        ordering = ['document_type']
        verbose_name = "Downloadable Document"
        verbose_name_plural = "Downloadable Documents"
