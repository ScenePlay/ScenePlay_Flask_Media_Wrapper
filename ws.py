from waitress import serve
import app
serve(app.app, host='0.0.0.0', port=8086, threads=8)
