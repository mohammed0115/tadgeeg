"""Frontend (template) views for file management."""
from django.contrib.auth.decorators import login_required
from django.shortcuts import render


@login_required
def files(request):
    return render(request, "phase2/files.html")


@login_required
def folders(request):
    return render(request, "phase2/folders.html")
