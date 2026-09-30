import os
import sys

from app import create_app
from app.demo import seed_demo_data
from app.extensions import db


app = create_app()


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "seed":
        with app.app_context():
            db.create_all()
            seed_demo_data()
        print("Dati demo creati.")
    else:
        app.run(
            host="127.0.0.1",
            port=int(os.environ.get("WIKIME_PORT", "5000")),
            debug=app.config["DEBUG"],
            use_reloader=False,
        )
