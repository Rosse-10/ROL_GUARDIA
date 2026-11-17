import shutil
import tempfile
from datetime import timedelta

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import (
    AusenciaLicencia, Carrera, DetalleGuardia, EsquemaGuardia, Estudiante, GuardiaDia, Puesto,
)

MEDIA_TEMPORAL = tempfile.mkdtemp()


@override_settings(MEDIA_ROOT=MEDIA_TEMPORAL)
class SolicitudAusenciaTests(TestCase):
    """Flujo completo: el cadete solicita -> el oficial aprueba/rechaza -> se marca DetalleGuardia"""

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA_TEMPORAL, ignore_errors=True)

    def setUp(self):
        self.hoy = timezone.localdate()
        carrera = Carrera.objects.create(nombre='SISTEMAS')
        # Estudiante.save() crea la cuenta: usuario = CI, contraseña = primer apellido en minúsculas
        self.cadete = Estudiante.objects.create(
            ci='9309384', nombres='RUDY', apellidos='CONDORI ESCOBAR', anio=3, carrera=carrera
        )
        self.otro = Estudiante.objects.create(
            ci='1111111', nombres='ANA', apellidos='PEREZ LOPEZ', anio=3, carrera=carrera
        )
        self.oficial = User.objects.create_superuser('oficial', password='clave-segura-123')

        esquema = EsquemaGuardia.objects.create(nombre='Esquema B', activo=True)
        puesto = Puesto.objects.create(esquema=esquema, nombre='Sargento de Guardia', cargo='SARGENTO', anio_requerido=3, orden=2)
        guardia = GuardiaDia.objects.create(fecha=self.hoy + timedelta(days=2), esquema=esquema)
        self.detalle = DetalleGuardia.objects.create(guardia=guardia, puesto=puesto, estudiante=self.cadete)

    def login_cadete(self):
        self.assertTrue(self.client.login(username='9309384', password='condori'))

    def enviar_solicitud(self, **extra):
        datos = {
            'tipo': 'SALUD',
            'fecha_inicio': self.hoy.isoformat(),
            'fecha_fin': (self.hoy + timedelta(days=3)).isoformat(),
            'motivo': 'Internado en el hospital',
            'justificativo': SimpleUploadedFile('ticket.jpg', b'\xff\xd8\xff fake-jpg', content_type='image/jpeg'),
        }
        datos.update(extra)
        return self.client.post(reverse('mis_solicitudes_ausencia'), datos)

    def test_estudiante_vinculado_con_su_usuario(self):
        self.assertEqual(self.cadete.usuario.username, '9309384')

    def test_cadete_envia_solicitud_y_queda_pendiente(self):
        self.login_cadete()
        respuesta = self.enviar_solicitud()
        self.assertRedirects(respuesta, reverse('mis_solicitudes_ausencia'))

        solicitud = AusenciaLicencia.objects.get()
        self.assertEqual(solicitud.estado, 'PENDIENTE')
        self.assertEqual(solicitud.estudiante, self.cadete)
        self.assertTrue(solicitud.justificativo.name.endswith('.jpg'))
        # Mientras esté pendiente, la guardia no cambia
        self.detalle.refresh_from_db()
        self.assertEqual(self.detalle.asistencia, 'PENDIENTE')

    def test_rechaza_fechas_invertidas_y_extension_invalida(self):
        self.login_cadete()
        self.enviar_solicitud(fecha_fin=(self.hoy - timedelta(days=1)).isoformat())
        self.enviar_solicitud(justificativo=SimpleUploadedFile('virus.exe', b'MZ'))
        self.assertFalse(AusenciaLicencia.objects.exists())

    def test_no_permite_solicitudes_superpuestas(self):
        self.login_cadete()
        self.enviar_solicitud()
        self.enviar_solicitud(fecha_inicio=(self.hoy + timedelta(days=1)).isoformat())
        self.assertEqual(AusenciaLicencia.objects.count(), 1)

    def test_cadete_no_accede_al_panel_del_oficial(self):
        self.login_cadete()
        respuesta = self.client.get(reverse('gestion_ausencias'))
        self.assertRedirects(respuesta, reverse('home'))

    def test_oficial_aprueba_y_se_marca_la_guardia(self):
        self.login_cadete()
        self.enviar_solicitud()
        solicitud = AusenciaLicencia.objects.get()

        self.client.login(username='oficial', password='clave-segura-123')
        self.client.post(reverse('gestion_ausencias'), {
            'accion': 'aprobar', 'solicitud_id': solicitud.id, 'observacion': 'Recupérese pronto',
        })

        solicitud.refresh_from_db()
        self.detalle.refresh_from_db()
        self.assertEqual(solicitud.estado, 'APROBADA')
        self.assertEqual(solicitud.resuelto_por, self.oficial)
        self.assertEqual(self.detalle.asistencia, 'LICENCIA')
        self.assertEqual(self.detalle.ausencia, solicitud)

        # El cadete ve su solicitud aprobada
        self.login_cadete()
        respuesta = self.client.get(reverse('mis_solicitudes_ausencia'))
        self.assertContains(respuesta, 'APROBADA')
        self.assertContains(respuesta, 'Recupérese pronto')

    def test_permiso_marca_con_permiso(self):
        self.login_cadete()
        self.enviar_solicitud(tipo='PERMISO_EMI')
        solicitud = AusenciaLicencia.objects.get()
        self.client.login(username='oficial', password='clave-segura-123')
        self.client.post(reverse('gestion_ausencias'), {'accion': 'aprobar', 'solicitud_id': solicitud.id})
        self.detalle.refresh_from_db()
        self.assertEqual(self.detalle.asistencia, 'PERMISO')

    def test_rechazo_exige_observacion_y_no_toca_la_guardia(self):
        self.login_cadete()
        self.enviar_solicitud()
        solicitud = AusenciaLicencia.objects.get()
        self.client.login(username='oficial', password='clave-segura-123')

        self.client.post(reverse('gestion_ausencias'), {'accion': 'rechazar', 'solicitud_id': solicitud.id})
        solicitud.refresh_from_db()
        self.assertEqual(solicitud.estado, 'PENDIENTE')

        self.client.post(reverse('gestion_ausencias'), {
            'accion': 'rechazar', 'solicitud_id': solicitud.id, 'observacion': 'Sin respaldo suficiente',
        })
        solicitud.refresh_from_db()
        self.detalle.refresh_from_db()
        self.assertEqual(solicitud.estado, 'RECHAZADA')
        self.assertEqual(self.detalle.asistencia, 'PENDIENTE')

        # No se puede volver a resolver una solicitud ya resuelta
        self.client.post(reverse('gestion_ausencias'), {'accion': 'aprobar', 'solicitud_id': solicitud.id})
        solicitud.refresh_from_db()
        self.assertEqual(solicitud.estado, 'RECHAZADA')

    def test_justificativo_solo_para_dueno_y_oficial(self):
        self.login_cadete()
        self.enviar_solicitud()
        url = reverse('ver_justificativo', args=[AusenciaLicencia.objects.get().id])
        self.assertEqual(self.client.get(url).status_code, 200)

        self.assertTrue(self.client.login(username='1111111', password='perez'))
        self.assertEqual(self.client.get(url).status_code, 404)

        self.client.login(username='oficial', password='clave-segura-123')
        self.assertEqual(self.client.get(url).status_code, 200)

    def test_oficial_registra_directo_y_queda_aprobada(self):
        self.client.login(username='oficial', password='clave-segura-123')
        self.client.post(reverse('gestion_ausencias'), {
            'accion': 'registrar', 'estudiante': self.cadete.id, 'tipo': 'COMISION',
            'fecha_inicio': self.hoy.isoformat(), 'fecha_fin': (self.hoy + timedelta(days=5)).isoformat(),
            'motivo': 'Comisión deportiva',
        })
        ausencia = AusenciaLicencia.objects.get()
        self.assertEqual(ausencia.estado, 'APROBADA')
        self.detalle.refresh_from_db()
        self.assertEqual(self.detalle.asistencia, 'PERMISO')
