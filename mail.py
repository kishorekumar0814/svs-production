# using SendGrid's Python Library
# https://github.com/sendgrid/sendgrid-python
import os
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail
from dotenv import load_dotenv

_env_path = os.path.join(os.path.dirname(__file__), ".env")
load_dotenv(dotenv_path=_env_path, override=False)

message = Mail(
    from_email=os.environ.get('SENDGRID_FROM_EMAIL', 'srivinayagastores2007@gmail.com'),
    to_emails=os.environ.get('SENDGRID_TO_EMAIL', 'kishorekumar1409@gmail.com'),
    subject='Sending with Twilio SendGrid is Fun',
    html_content='<strong>and easy to do anywhere, even with Python</strong>')
try:
    api_key = os.environ.get('SENDGRID_API_KEY')
    if not api_key:
        raise RuntimeError("SENDGRID_API_KEY is not set")
    sg = SendGridAPIClient(api_key)
    # sg.set_sendgrid_data_residency("eu")
    # uncomment the above line if you are sending mail using a regional EU subuser
    response = sg.send(message)
    print(response.status_code)
    print(response.body)
    print(response.headers)
except Exception as e:
    print(str(e))
