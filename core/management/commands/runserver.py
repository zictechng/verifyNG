from django.contrib.staticfiles.management.commands.runserver import Command as StaticfilesRunserverCommand


class Command(StaticfilesRunserverCommand):
    """
    Overridden runserver command that automatically binds to 0.0.0.0:8000 in development.
    Allows both localhost and mobile devices on the local Wi-Fi to connect automatically.
    """
    default_addr = '0.0.0.0'
    default_port = '8000'
