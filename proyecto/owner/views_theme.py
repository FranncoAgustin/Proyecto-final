# owner/views_theme.py
from django.http import HttpResponse
from .models import SiteConfig

def theme_css(request):
    cfg = SiteConfig.get_solo()
    css = f"""
:root {{
  --mp-primary: {cfg.primary_color};
  --mp-secondary: {cfg.secondary_color};
  --mp-success: {cfg.success_color};
  --mp-danger: {cfg.danger_color};
  --mp-bg: {cfg.background};
  --mp-surface: {cfg.surface};
  --mp-text: {cfg.text_color};

  --mp-font-base: {cfg.font_base};
  --mp-font-headings: {cfg.font_headings};
}}

body {{
  background: var(--mp-bg);
  color: var(--mp-text);
  font-family: var(--mp-font-base);
}}

h1,h2,h3,h4,h5,h6 {{
  font-family: var(--mp-font-headings);
}}

.btn-primary {{
  background-color: var(--mp-primary) !important;
  border-color: var(--mp-primary) !important;
}}
"""
    return HttpResponse(css, content_type="text/css")
