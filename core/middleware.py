from django.shortcuts import render

class Friendly404Middleware:
    """
    Ensures that whenever any user visits an unknown or non-existent URL,
    they are presented with the clean, branded VerifyNG 404 page rather than
    raw Django debug codes, stack traces, or technical URL patterns in the browser.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if response.status_code == 404:
            # Preserve API JSON error responses
            if request.path.startswith('/api/'):
                return response

            content_type = response.get('Content-Type', '')
            if 'text/html' in content_type:
                return render(request, '404.html', status=404)

        return response
