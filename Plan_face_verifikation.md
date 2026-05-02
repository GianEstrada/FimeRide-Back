FimeRide — AWS Rekognition Integration Plan
Implementation spec for a coding agent · Django 5.1 backend · Existing S3 + PostgreSQL infrastructure

Backend: Django 5.1
AWS Rekognition
Amazon S3
PostgreSQL
4 new endpoints
2 modified endpoints
Goals
Goal 1
Automate face verification on login using Rekognition CompareFaces — compare a live photo against the stored S3 profile image.

Goal 2
Verify that the credential photo submitted at registration matches the user's profile photo using CompareFaces.

Goal 3
Validate an active enrollment period by reading the barcode/text of the rectoría PDF using pyzbar + Rekognition DetectText fallback.

Goal 4
Allow users to update their profile photo post-registration, uploading a new image to S3 and re-validating face quality.

Goal 5
Ensure no endpoint blocking — every Rekognition failure degrades gracefully with a clear error response and an admin alert flag, never a hard crash.

New & modified endpoints
POST
/api/login/
Modified
New request fields
username — matricula (existing)
password — string (existing)
foto_live — multipart file, optional JPEG/PNG
New behavior
If foto_live present: call verify_face_present() then compare_faces_s3()
Similarity < threshold → HTTP 403 with similarity field
Rekognition failure → log warning, proceed with login (do not block)
Return existing JWT payload unchanged on success
If foto_live is absent, login proceeds as before — backwards compatible. Face check is opt-in at this stage.

POST
/api/registrar/
Modified
Existing fields (unchanged)
nombre_completo, correo_universitario
matricula, contraseña
foto_perfil, credencial_frontal, credencial_trasera
boleta_rectoria, solicito_conductor
New behavior (added to existing transaction)
After saving files: call verify_face_present(foto_perfil) — store result in DB
Call compare_faces_bytes(foto_perfil, credencial_frontal) — store similarity score
Call extract_matricula_from_pdf(boleta_rectoria, matricula) — store boolean result
All AI results are stored but do not block registration — admin sees them in Django Admin
Add fields ai_face_match (bool), ai_face_similarity (float), ai_boleta_valid (bool) to DocumentacionPasajero or a new RegistrationAIResult model.

POST
/api/verificar_credencial/
New
Request — multipart/form-data
usuario_id — integer, required
credencial_frontal — file, required (JPEG/PNG)
Response
match — boolean
similarity — float (0–100)
message — human-readable string
Saves result to DocumentacionPasajero.autorizado
Source image: user's foto_perfil from S3 (key from DB). Target: uploaded credencial_frontal bytes. Uses compare_faces_s3(s3_key, target_bytes).

POST
/api/verificar_boleta/
New
Request — multipart/form-data
usuario_id — integer, required
boleta_pdf — file, required (PDF)
Response
valid — boolean (matricula found in document)
detected_text — extracted string (truncated)
method — "barcode" or "ocr"
Updates DocumentacionPasajero.autorizado for boleta record
Primary: pyzbar barcode decode on pdf2image render. Fallback: Rekognition DetectText on first page as JPEG. Method field tells the caller which path was used.

PATCH
/api/usuario/<usuario_id>/foto/
New
Request — multipart/form-data
foto_perfil — file, required (JPEG/PNG, max 5MB)
Authenticated: requires valid JWT in Authorization header
Users may only update their own photo (validate token subject = usuario_id)
Behavior
Run verify_face_present() on new photo — reject if no face detected
Delete old S3 object (fotos_perfil/old_key)
Upload new photo to S3 under fotos_perfil/<uuid>.jpg
Update Usuario.foto_perfil field in DB
Return new foto_url (public S3 URL)
Use UUID-based filenames to bust CDN/browser caches. Delete old file from S3 before writing new one to avoid orphan objects in the bucket.

GET
/api/usuario/<usuario_id>/ai_status/
New
Purpose
Expose AI verification results to admin panel / flutter app
No request body required
Response
face_present — bool
credential_match — bool, float similarity
boleta_valid — bool
profile_photo_url — current S3 URL
Read-only. Useful for the Flutter app to show verification badges on the user profile screen.

Implementation requirements
New Python files
Create usuarios/rekognition_service.py
Create usuarios/barcode_service.py
Add migration for new AI result fields
rekognition_service.py must expose
compare_faces_s3(s3_key, target_bytes) → (bool, float)
compare_faces_bytes(source_bytes, target_bytes) → (bool, float)
verify_face_present(image_bytes) → (bool, str)
Single shared boto3.client("rekognition") at module level
All functions raise a typed RekognitionError on AWS errors
barcode_service.py must expose
extract_matricula_from_pdf(pdf_bytes, matricula) → (bool, str, str method)
Primary path: pyzbar on pdf2image render (dpi=200)
Fallback path: Rekognition DetectText on first page JPEG
Return which method succeeded via method field
Database changes
Add ai_face_present BooleanField (null=True) to Usuario
Add ai_face_similarity FloatField (null=True) to DocumentacionPasajero
Add ai_boleta_valid BooleanField (null=True) to DocumentacionPasajero
New migration: 0003_ai_verification_fields
Environment variables
AWS_ACCESS_KEY_ID — already exists
AWS_SECRET_ACCESS_KEY — already exists
AWS_REKOGNITION_REGION — add, default us-east-2
FACE_SIMILARITY_THRESHOLD — add, default 80
S3 bucket name: read from existing AWS_STORAGE_BUCKET_NAME
New pip dependencies
pyzbar>=0.1.9 — barcode decoding
pdf2image>=1.17.0 — PDF→image conversion
boto3>=1.34.0 — already present, verify
System package: poppler-utils (for pdf2image on Render)
Add Render build command: apt-get install -y poppler-utils libzbar0
IAM permissions to add
rekognition:CompareFaces
rekognition:DetectFaces
rekognition:DetectText
Resource: * (Rekognition has no resource-level ARNs)
S3: add s3:DeleteObject for profile photo updates
URL routing — add to urls.py
path("api/verificar_credencial/", ...)
path("api/verificar_boleta/", ...)
path("api/usuario/<int:uid>/foto/", ...)
path("api/usuario/<int:uid>/ai_status/", ...)
S3 profile photo update — full flow
Step	Action	Details
1	Validate JWT	Token subject must equal usuario_id in path — reject HTTP 403 if mismatch
2	Validate file	Accept JPEG/PNG only. Max 5MB. Reject with HTTP 400 if invalid type or size exceeded.
3	Face check	Run verify_face_present(file.read()) — reject HTTP 400 with reason string if no face or low quality
4	Build S3 key	Generate fotos_perfil/{uuid4()}.jpg — never reuse old key
5	Upload new	Use S3Boto3Storage or boto3.put_object() with ContentType: image/jpeg
6	Delete old	If usuario.foto_perfil is set, call s3.delete_object(Bucket=..., Key=old_key)
7	Update DB	Set usuario.foto_perfil = new_key and save. Do DB write after S3 upload succeeds.
8	Return	HTTP 200 with {"foto_url": "https://..."} — full public S3 URL
Non-functional constraints
Security
All new endpoints must be decorated with @csrf_exempt (consistent with existing API pattern). Migrate to JWT auth for all new endpoints using djangorestframework-simplejwt.
Security
The photo update endpoint must verify token ownership — a user must not be able to update another user's photo. Validate token.usuario_id == path.usuario_id.
Security
Never log or store the image bytes themselves. Log only: timestamp, usuario_id, operation name, similarity score, and success/failure. No PII in logs.
Performance
Rekognition calls happen synchronously in the request cycle. The /api/login/ face check must not add more than ~2s latency. Use read() once and pass bytes — do not re-open the file.
Performance
pdf2image with dpi=200 can be slow for large PDFs. Process only the first page: convert_from_bytes(pdf_bytes, dpi=200, first_page=1, last_page=1).
Error handling
Wrap every Rekognition call in try/except. On ClientError: log the error, set a flag in DB if applicable, and return a graceful response. Never propagate a raw AWS exception to the client.
Error handling
The registration endpoint (/api/registrar/) must remain atomic. AI verification failures should NOT roll back the user record — store null for the AI fields and let the admin decide.
Compatibility
All changes to /api/login/ and /api/registrar/ must be backwards compatible. Clients that do not send foto_live or AI fields must continue to work exactly as before.
Compatibility
The S3 bucket (fimeridearchivos) stays the same. New profile photos go in fotos_perfil/ prefix — same as existing. No bucket policy changes needed for uploads.
Files to create or modify
usuarios/rekognition_service.py
New. Three exported functions. Module-level boto3 client. Custom RekognitionError exception class.

usuarios/barcode_service.py
New. One exported function with pyzbar primary path and Rekognition DetectText fallback.

usuarios/views.py
Modify login_view and registrar_view. Add four new view functions: verificar_credencial, verificar_boleta, update_profile_photo, get_ai_status.

usuarios/models.py
Add ai_face_present, ai_face_similarity, ai_boleta_valid fields. Keep null=True, blank=True on all — non-blocking.

usuarios/urls.py
Add four new path() entries for the new endpoints.

usuarios/migrations/0003_ai_verification_fields.py
New Django migration for the three new model fields.

requirements.txt
Add pyzbar>=0.1.9 and pdf2image>=1.17.0. Verify boto3 is present.

render.yaml or build script
Add apt-get install poppler-utils libzbar0 to the Render build command so pdf2image and pyzbar have their native dependencies.

