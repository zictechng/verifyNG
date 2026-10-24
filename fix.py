with open('templates/employer/dashboard.html', 'rb') as f:
    data = f.read()

target = b'<div class="col-6 col-md-4">\r\n        <div class="col-6 col-md-4">'
replacement = b'<div class="col-6 col-md-4">'
if target not in data:
    target = b'<div class="col-6 col-md-4">\n        <div class="col-6 col-md-4">'

if target in data:
    data = data.replace(target, replacement, 1)
    with open('templates/employer/dashboard.html', 'wb') as f:
        f.write(data)
    print("Deduplicated successfully!")
else:
    print("Target not found in bytes!")
