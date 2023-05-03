from dotenv import load_dotenv
from gbtalks import create_app
import os

project_folder = os.path.expanduser('~/talks-processing')  # adjust as appropriate
load_dotenv(os.path.join(project_folder, '.env'))

app = create_app()

if __name__ == "__main__":
    app.run(host='0.0.0.0')
