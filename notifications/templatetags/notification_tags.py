
# notifications/templatetags/notification_tags.py
from django import template

register = template.Library()


@register.filter(name='getattr')
def getattr_filter(obj, attr):
    """Allow {{ obj|getattr:'field_name' }} in templates."""
    return getattr(obj, attr, False)

