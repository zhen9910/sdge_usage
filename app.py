from flask import Flask, render_template, request, flash, redirect, url_for
from sdge_usage import (
    process,
    iter_rows_csv_stream,
    iter_rows_xlsx_stream,
)

app = Flask(__name__)
app.secret_key = "sdge-usage-secret"

ALLOWED_EXTENSIONS = {"csv", "xlsx"}


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        file = request.files.get("file")
        if not file or file.filename == "":
            flash("Please select a file.", "danger")
            return redirect(url_for("index"))

        if not allowed_file(file.filename):
            flash("Only .csv and .xlsx files are supported.", "danger")
            return redirect(url_for("index"))

        ext = file.filename.rsplit(".", 1)[1].lower()
        try:
            if ext == "csv":
                rows = iter_rows_csv_stream(file.stream)
            else:
                rows = iter_rows_xlsx_stream(file.stream)
            result = process(rows)
            result["filename"] = file.filename
            return render_template("result.html", result=result)
        except Exception as e:
            flash(f"Error processing file: {e}", "danger")
            return redirect(url_for("index"))

    return render_template("index.html")


if __name__ == "__main__":
    app.run(debug=True)
