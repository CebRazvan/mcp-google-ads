"""Inline HTML for the OAuth login flow. No template engine dependency."""

HTML_LOGIN_FORM = """\
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Sign in - Google Ads MCP</title>
  <style>
    html, body {{ height: 100%; margin: 0; background: #0f172a; color: #e2e8f0;
                  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
    .wrap {{ display: flex; align-items: center; justify-content: center; min-height: 100vh; }}
    .card {{ background: #1e293b; padding: 2rem; border-radius: 10px; width: 320px;
             box-shadow: 0 10px 30px rgba(0,0,0,.3); }}
    h1 {{ font-size: 1.15rem; font-weight: 600; margin: 0 0 1rem 0; }}
    p.sub {{ color: #94a3b8; font-size: .85rem; margin: 0 0 1.25rem 0; }}
    label {{ display: block; font-size: .8rem; color: #cbd5e1; margin: .75rem 0 .25rem 0; }}
    input {{ width: 100%; padding: .55rem .7rem; border-radius: 6px; border: 1px solid #334155;
             background: #0f172a; color: #e2e8f0; font-size: .95rem; box-sizing: border-box; }}
    input:focus {{ outline: none; border-color: #64748b; }}
    button {{ width: 100%; margin-top: 1.25rem; padding: .6rem; border-radius: 6px; border: none;
              background: #3b82f6; color: white; font-weight: 600; font-size: .95rem; cursor: pointer; }}
    button:hover {{ background: #2563eb; }}
    .err {{ margin-top: .75rem; color: #fca5a5; font-size: .85rem; }}
  </style>
</head>
<body>
  <div class="wrap">
    <form class="card" method="post" action="/oauth/login">
      <h1>Google Ads MCP</h1>
      <p class="sub">Sign in to connect Claude to Google Ads.</p>
      <input type="hidden" name="session" value="{session}">
      <input type="hidden" name="csrf" value="{csrf}">
      <label for="u">Username</label>
      <input id="u" name="username" type="text" autocomplete="username" autofocus required>
      <label for="p">Password</label>
      <input id="p" name="password" type="password" autocomplete="current-password" required>
      <button type="submit">Sign in</button>
      <div class="err">{error}</div>
    </form>
  </div>
</body>
</html>
"""

HTML_ERROR = """\
<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Error</title>
<style>body {{ font-family: system-ui, sans-serif; background: #0f172a; color: #e2e8f0;
  display: flex; align-items: center; justify-content: center; height: 100vh; margin: 0; }}
.box {{ background: #1e293b; padding: 2rem; border-radius: 10px; max-width: 400px; }}
</style></head>
<body><div class="box"><strong>Error.</strong><br>{message}</div></body></html>
"""
