from django.contrib import admin
from .models import (
	    PatientProfile, ConsultationForm, Appointment, 
	    SessionRecord, ClinicalAssessment, TherapistProfile, Document,
	    FeedbackQuestion, FeedbackSubmission, FeedbackAnswer, PaymentTransaction
)

# ============= PATIENT PROFILE =============
@admin.register(PatientProfile)
class PatientProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'phone_number', 'gender', 'consent_form_signed', 'created_at')
    list_filter = ('gender', 'consent_form_signed', 'created_at')
    search_fields = ('user__first_name', 'user__last_name', 'phone_number')
    readonly_fields = ('created_at', 'updated_at')
    fieldsets = (
        ('User Information', {
            'fields': ('user',)
        }),
        ('Personal Information', {
            'fields': ('phone_number', 'date_of_birth', 'gender', 'address')
        }),
        ('Emergency Contact', {
            'fields': ('emergency_contact', 'emergency_contact_name')
        }),
        ('Medical History', {
            'fields': ('medical_history', 'current_medications', 'allergies'),
            'classes': ('collapse',)
        }),
        ('Consent & Forms', {
            'fields': ('consent_form_signed', 'consent_form_date', 'biodata_complete')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


# ============= CONSULTATION FORM =============
@admin.register(ConsultationForm)
class ConsultationFormAdmin(admin.ModelAdmin):
    list_display = ('patient', 'form_type', 'is_signed', 'signed_date', 'created_at')
    list_filter = ('form_type', 'is_signed', 'created_at')
    search_fields = ('patient__user__first_name', 'patient__user__last_name')
    readonly_fields = ('created_at', 'updated_at')


# ============= APPOINTMENT =============
@admin.register(Appointment)
class AppointmentAdmin(admin.ModelAdmin):
    list_display = ('patient', 'appointment_date', 'therapist', 'status', 'duration_minutes')
    list_filter = ('status', 'appointment_date', 'created_at')
    search_fields = ('patient__user__first_name', 'patient__user__last_name', 'therapist__first_name')
    readonly_fields = ('created_at', 'updated_at')
    fieldsets = (
        ('Appointment Details', {
            'fields': ('patient', 'therapist', 'appointment_date', 'duration_minutes', 'status')
        }),
        ('Additional Information', {
            'fields': ('notes', 'cancellation_reason')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


# ============= SESSION RECORD =============
@admin.register(SessionRecord)
class SessionRecordAdmin(admin.ModelAdmin):
    list_display = ('patient', 'appointment', 'session_date', 'payment_status', 'amount')
    list_filter = ('payment_status', 'session_date', 'currency')
    search_fields = ('patient__user__first_name', 'patient__user__last_name')
    readonly_fields = ('created_at', 'updated_at', 'session_date')
    fieldsets = (
        ('Session Information', {
            'fields': ('patient', 'appointment', 'therapist', 'session_date')
        }),
        ('Billing', {
            'fields': ('amount', 'currency', 'payment_status', 'payment_date', 'payment_method')
        }),
        ('Notes', {
            'fields': ('session_notes',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


# ============= CLINICAL ASSESSMENT =============
@admin.register(ClinicalAssessment)
class ClinicalAssessmentAdmin(admin.ModelAdmin):
    list_display = ('patient', 'assessment_type', 'therapist', 'is_visible_to_patient', 'created_at')
    list_filter = ('assessment_type', 'is_visible_to_patient', 'created_at')
    search_fields = ('patient__user__first_name', 'patient__user__last_name', 'title')
    readonly_fields = ('created_at', 'updated_at')
    fieldsets = (
        ('Assessment Information', {
            'fields': ('patient', 'session_record', 'therapist', 'assessment_type', 'title')
        }),
        ('Content', {
            'fields': ('content',)
        }),
        ('Visibility', {
            'fields': ('is_visible_to_patient', 'date_shared')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


# ============= THERAPIST PROFILE =============
@admin.register(TherapistProfile)
class TherapistProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'license_number', 'specialization', 'hourly_rate', 'is_available')
    list_filter = ('specialization', 'is_available', 'created_at')
    search_fields = ('user__first_name', 'user__last_name', 'license_number')
    readonly_fields = ('created_at', 'updated_at')
    fieldsets = (
        ('User Information', {
            'fields': ('user',)
        }),
        ('Professional Information', {
            'fields': ('license_number', 'specialization', 'bio', 'phone_number')
        }),
        ('Practice Settings', {
            'fields': ('hourly_rate', 'session_duration', 'is_available')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


# ============= DOWNLOADABLE DOCUMENTS =============
@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = ('get_document_type_display', 'title', 'file', 'updated_at')
    list_filter = ('document_type', 'created_at', 'updated_at')
    search_fields = ('title', 'description')
    readonly_fields = ('created_at', 'updated_at')
    fieldsets = (
        ('Document Information', {
            'fields': ('document_type', 'title', 'description')
        }),
        ('File Upload', {
            'fields': ('file',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


# ============= FEEDBACK =============
@admin.register(FeedbackQuestion)
class FeedbackQuestionAdmin(admin.ModelAdmin):
    list_display = ("prompt", "question_type", "sort_order", "is_active")
    list_filter = ("question_type", "is_active")
    search_fields = ("prompt",)
    ordering = ("sort_order", "id")


class FeedbackAnswerInline(admin.TabularInline):
    model = FeedbackAnswer
    extra = 0


@admin.register(FeedbackSubmission)
class FeedbackSubmissionAdmin(admin.ModelAdmin):
    list_display = ("patient", "session_record", "appointment", "submitted_at")
    list_filter = ("submitted_at",)
    search_fields = ("patient__user__first_name", "patient__user__last_name", "comment")
    readonly_fields = ("submitted_at",)
    inlines = (FeedbackAnswerInline,)


# ============= PAYMENTS =============
@admin.register(PaymentTransaction)
class PaymentTransactionAdmin(admin.ModelAdmin):
    list_display = ("session_record", "amount", "phone_number", "status", "initiated_at", "checkout_request_id")
    list_filter = ("status", "initiated_at")
    search_fields = ("session_record__patient__user__first_name", "session_record__patient__user__last_name", "checkout_request_id", "mpesa_receipt_number")
    readonly_fields = ("initiated_at", "updated_at", "callback_payload")
