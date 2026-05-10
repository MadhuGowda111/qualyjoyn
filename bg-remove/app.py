from flask import Flask, request, send_file
from flask_cors import CORS
from rembg import remove
from PIL import Image, ImageFilter
import io

app = Flask(__name__)

CORS(app)


# Home Route
@app.route("/")
def home():

    return "AI Background Remover Backend Running"


# Background Remove Route
@app.route("/remove-bg", methods=["POST"])
def remove_bg():

    try:

        file = request.files["image"]

        input_image = Image.open(file).convert("RGBA")

        # Resize Large Images
        max_size = (1500, 1500)

        input_image.thumbnail(max_size)

        # AI Background Removal
        output_image = remove(
            input_image,
            alpha_matting=True,
            alpha_matting_foreground_threshold=220,
            alpha_matting_background_threshold=20,
            alpha_matting_erode_size=3
        )

        # Smooth Edges
        output_image = output_image.filter(
            ImageFilter.SMOOTH_MORE
        )

        # Remove White Edge Halo
        # Advanced Edge Cleanup

        datas = output_image.getdata()

        newData = []

        for item in datas:

            r, g, b, a = item

            # Remove white/light transparent halo
            if (
                r > 180 and
                g > 180 and
                b > 180 and
                a < 240
            ):

                newData.append((255, 255, 255, 0))

            # Remove very transparent pixels
            elif a < 25:

                newData.append((255, 255, 255, 0))

            # Slightly sharpen semi-transparent edges
            elif a < 120:

                newData.append((r, g, b, int(a * 0.6)))

            else:

                newData.append(item)

        output_image.putdata(newData)

        img_io = io.BytesIO()

        output_image.save(
            img_io,
            format="PNG"
        )

        img_io.seek(0)

        return send_file(
            img_io,
            mimetype="image/png"
        )

    except Exception as e:

        return {
            "status": "error",
            "message": str(e)
        }, 500


if __name__ == "__main__":

    app.run(debug=True)