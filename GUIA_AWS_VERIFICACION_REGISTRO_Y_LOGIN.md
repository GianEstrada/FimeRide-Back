# Guia AWS para verificacion de documentos e identidad

## 1) Servicios AWS necesarios
- Amazon S3: almacenamiento de foto de perfil, credencial y boleta.
- Amazon Rekognition: comparacion facial y OCR simple en imagenes.
- Amazon Textract: lectura de texto en PDF (boleta).

Nota importante:
- Solo con Rekognition no se puede validar PDF de forma robusta. Para boleta en PDF se requiere Textract.

## 2) Flujo de registro implementado
1. App envia formulario con:
   - foto_perfil
   - credencial_frontal
   - credencial_trasera
   - boleta_rectoria (PDF)
2. Backend ejecuta validacion automatica:
   - Textract detecta texto de boleta y valida BOLETA PAGADA/PAGADO.
   - OCR revisa matricula en boleta y credencial frontal.
   - Rekognition CompareFaces compara credencial frontal vs foto_perfil.
3. Si pasa todo:
   - Se guarda usuario.
   - Se guardan documentos en S3 (via django-storages).
   - Se guarda auditoria en VerificacionIdentidad.
4. Si falla:
   - Registro rechazado con motivo detallado.

## 3) Flujo de login con imagen en vivo
1. Usuario inicia sesion con matricula/contrasena.
2. App solicita captura en camara (no galeria).
3. App envia imagen_viva al endpoint login_face_match.
4. Backend compara foto_perfil aprobada vs imagen_viva con Rekognition.
5. Si coincide: acceso permitido.
6. Si no coincide: acceso denegado.

## 4) Configuracion en AWS (paso a paso)
1. Crear bucket S3 (o reutilizar existente).
2. Crear usuario IAM para backend con permisos:
   - s3:GetObject, s3:PutObject, s3:ListBucket
   - rekognition:CompareFaces, rekognition:DetectText
   - textract:DetectDocumentText
3. Guardar credenciales en variables de entorno del backend.
4. Validar acceso desde servidor (opcional con AWS CLI):
   - aws s3 ls
   - aws rekognition list-collections --region us-east-2
   - aws textract detect-document-text --document Bytes=fileb://prueba.pdf

## 5) Variables de entorno
- AWS_ACCESS_KEY_ID
- AWS_SECRET_ACCESS_KEY
- REKOGNITION_SIMILARITY_THRESHOLD=90
- REKOGNITION_LOGIN_SIMILARITY_THRESHOLD=90

## 6) Endpoints nuevos/relevantes
- POST /api/registrar/
  - Valida boleta + matricula + face match de registro
- POST /api/login_face_match/
  - Valida identidad en vivo al entrar

## 7) Recomendaciones para produccion
- Usar KMS en S3.
- Restringir IAM por bucket y prefijos.
- Activar CloudWatch para auditoria de errores.
- Agregar reintentos y timeout controlados para AWS.
- Enmascarar datos sensibles en logs.
