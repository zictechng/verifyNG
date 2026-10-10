from django.shortcuts import render
from django.http import HttpResponse
from core.rate_limiting import check_rate_limit


def home(request):
    return render(request, 'public/home.html')

def check(request):
    is_limited, retry_after = check_rate_limit(request, namespace="web_check")
    if is_limited:
        response = HttpResponse(
            "Rate limit exceeded. Please wait before retrying.",
            status=429,
            content_type="text/plain; charset=utf-8"
        )
        response['Retry-After'] = str(retry_after)
        return response

    return render(request, 'public/check.html')


def report(request):
    return render(request, 'public/report.html')


def verify(request):
    return render(request, 'public/verify.html')

