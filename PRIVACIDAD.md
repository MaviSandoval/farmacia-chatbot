# Política de privacidad — Asistente de Farmacia (demo)

**Última actualización:** 3 de octubre de 2026

Este asistente es un **proyecto de demostración con fines educativos**, desarrollado por María Victoria Sandoval. No pertenece a una farmacia real: los productos, precios, coberturas y sucursales son ficticios.

## Qué datos se procesan

Cuando le escribís al asistente por la web, Telegram o WhatsApp, se procesan:

- **El texto de tus mensajes**, para poder responderte.
- **Tu identificador en el canal** (número de teléfono en WhatsApp o identificador de chat en Telegram), solo para mantener el hilo de la conversación y enviarte la respuesta.

El asistente no pide ni necesita datos personales, de salud ni de pago. **No compartas información sensible** (diagnósticos, recetas, datos de obra social, documentos).

## Para qué se usan

Únicamente para generar la respuesta a tu consulta. No se usan con fines publicitarios ni se venden o ceden a terceros.

## Con quién se comparten

Para funcionar, el asistente utiliza estos servicios, que procesan los mensajes según sus propias políticas:

- **Groq**: genera las respuestas con un modelo de lenguaje. Recibe el texto de la conversación, sin tu número de teléfono.
- **Meta (WhatsApp Cloud API)**, **Twilio** y **Telegram**: transportan los mensajes del canal que elijas.
- **Render** y **Streamlit Community Cloud**: alojan la aplicación.

## Cuánto tiempo se conservan

- El historial de cada conversación se guarda **solo en la memoria del servidor** y se borra cuando el servidor se reinicia (ocurre automáticamente tras un período de inactividad). No hay una base de datos de conversaciones.
- Los registros técnicos del servidor pueden incluir temporalmente el identificador del canal y el texto del mensaje, y se eliminan según la retención del servicio de alojamiento.

## Cómo borrar tus datos

- Enviá el mensaje **`reiniciar`** para borrar el historial de tu conversación en el momento.
- Para cualquier otro pedido o consulta sobre tus datos, abrí un *issue* en el repositorio: <https://github.com/MaviSandoval/farmacia-chatbot/issues>

## Aviso importante

El asistente brinda información general de una farmacia ficticia. **No reemplaza la consulta con un médico o farmacéutico** y no debe usarse para tomar decisiones de salud.
