from django.shortcuts import render

def home(request):
    return render(request, 'clinic/home.html')
