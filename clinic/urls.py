from django.urls import path
from . import views

urlpatterns = [
    # Public pages
    path('', views.home, name='home'),
    path('book/', views.book_appointment_redirect, name='book_appointment_redirect'),
    path('download/<str:doc_type>/', views.download_document, name='download_document'),
    
    # Patient Authentication
    path('register/', views.patient_register, name='patient_register'),
    path('login/', views.patient_login, name='patient_login'),
    path('logout/', views.patient_logout, name='patient_logout'),
    
    # Patient Portal
    path('dashboard/', views.patient_dashboard, name='patient_dashboard'),
    path('profile/', views.patient_profile, name='patient_profile'),
    path('appointments/', views.patient_appointments, name='patient_appointments'),
    path('assessments/', views.patient_assessments, name='patient_assessments'),
    path('assessment/<int:assessment_id>/', views.assessment_detail, name='assessment_detail'),
    
    # Booking System
    path('booking/', views.booking_calendar, name='booking_calendar'),
    path('booking/create/', views.create_booking, name='create_booking'),
    path('booking/<int:appointment_id>/confirm/', views.booking_confirmation, name='booking_confirmation'),
    path('booking/<int:appointment_id>/cancel/', views.cancel_booking, name='cancel_booking'),
    
    # API/Components
    path('api/upcoming-sessions/', views.get_upcoming_sessions, name='get_upcoming_sessions'),
    path('api/check-availability/', views.check_availability, name='check_availability'),
    
    # Therapist Authentication
    path('therapist/login/', views.therapist_login, name='therapist_login'),
    path('therapist/logout/', views.therapist_logout, name='therapist_logout'),
    
    # Therapist Dashboard
    path('therapist/dashboard/', views.therapist_dashboard, name='therapist_dashboard'),
    path('therapist/patients/', views.therapist_patients, name='therapist_patients'),
    path('therapist/patient/<int:patient_id>/', views.patient_detail, name='patient_detail'),
    path('therapist/patient/<int:patient_id>/assessment/', views.create_assessment, name='create_assessment'),
    
    # Appointments Management
    path('therapist/appointments/', views.manage_appointments, name='manage_appointments'),
    path('therapist/appointment/<int:appointment_id>/update/', views.update_appointment_status, name='update_appointment_status'),
    
    # Billing
    path('therapist/billing/', views.billing_dashboard, name='billing_dashboard'),
    path('therapist/session/<int:session_id>/payment/', views.update_payment_status, name='update_payment_status'),
]
