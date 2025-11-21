# Proyecto_final
Proyecto final de la tecnicatura 

# Crear entorno virtual
python -m venv .venv

# Activar entorno virtual
# En Windows:
.\.venv\Scripts\activate

pip install django

# pip install -r requirements.txt 
python manage.py migrate 
python manage.py makemigrations
python manage.py runserver