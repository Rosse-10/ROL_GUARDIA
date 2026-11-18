import shutil
import tempfile
from datetime import timedelta

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import (
    AusenciaLicencia, Carrera, DetalleGuardia, EsquemaGuardia, Estudiante, Gestion, GuardiaDia, Puesto,
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
        carrera = Carrera.objects.get(nombre='SISTEMAS')
        # Estudiante.save() crea la cuenta: usuario = CI, contraseña = primer apellido en minúsculas
        self.cadete = Estudiante.objects.create(
            ci='9309384', nombres='RUDY', apellidos='CONDORI ESCOBAR', anio=3, carrera=carrera
        )
        self.otro = Estudiante.objects.create(
            ci='1111111', nombres='ANA', apellidos='PEREZ LOPEZ', anio=3, carrera=carrera
        )
        Estudiante.objects.update(debe_cambiar_clave=False)  # Ya cambiaron su clave inicial
        self.oficial = User.objects.create_superuser('oficial', password='clave-segura-123')

        esquema = EsquemaGuardia.objects.create(nombre='Esquema B')
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


class PermisosOficialTests(TestCase):
    """Solo los oficiales (superusuario o grupo 'Oficial') pueden administrar el sistema"""

    def setUp(self):
        from django.contrib.auth.models import Group
        from .permisos import GRUPO_OFICIAL

        carrera = Carrera.objects.get(nombre='CIVIL')
        self.cadete = Estudiante.objects.create(
            ci='2222222', nombres='LUIS', apellidos='MAMANI QUISPE', anio=2, carrera=carrera
        )
        Estudiante.objects.update(debe_cambiar_clave=False)
        self.esquema = EsquemaGuardia.objects.create(nombre='Esquema A')
        self.gestion = Gestion.objects.create(
            nombre='Gestión 2026', fecha_inicio='2026-02-01', fecha_fin='2026-12-15'
        )
        oficial = User.objects.create_user('teniente', password='clave-segura-123')
        oficial.groups.add(Group.objects.get(name=GRUPO_OFICIAL))  # El grupo lo crea la migración 0009

        self.urls_admin = [
            reverse('lista_estudiantes'),
            reverse('nuevo_estudiante'),
            reverse('editar_estudiante', args=[self.cadete.id]),
            reverse('eliminar_estudiante', args=[self.cadete.id]),
            reverse('lista_gestiones'),
            reverse('nueva_gestion'),
            reverse('editar_gestion', args=[self.gestion.id]),
            reverse('lista_esquemas'),
            reverse('nuevo_esquema'),
            reverse('editar_esquema', args=[self.esquema.id]),
            reverse('planificacion_guardias'),
            reverse('gestion_ausencias'),
        ]

    def test_cadete_no_accede_a_modulos_de_administracion(self):
        self.assertTrue(self.client.login(username='2222222', password='mamani'))
        for url in self.urls_admin:
            with self.subTest(url=url):
                self.assertRedirects(self.client.get(url), reverse('home'))

    def test_cadete_no_puede_borrar_ni_generar(self):
        self.client.login(username='2222222', password='mamani')
        self.client.post(reverse('eliminar_estudiante', args=[self.cadete.id]))
        self.client.post(reverse('eliminar_gestion', args=[self.gestion.id]))
        self.client.post(reverse('eliminar_esquema', args=[self.esquema.id]))
        self.client.post(reverse('generar_rango_guardias'), {'fecha_inicio': '2026-03-01', 'fecha_fin': '2026-03-05'})
        self.assertTrue(Estudiante.objects.filter(id=self.cadete.id).exists())
        self.assertTrue(Gestion.objects.filter(id=self.gestion.id).exists())
        self.assertTrue(EsquemaGuardia.objects.filter(id=self.esquema.id).exists())
        self.assertFalse(GuardiaDia.objects.exists())

    def test_oficial_del_grupo_accede(self):
        self.assertTrue(self.client.login(username='teniente', password='clave-segura-123'))
        for url in self.urls_admin:
            if 'eliminar' in url:
                continue
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_eliminar_gestion_y_esquema_exige_post(self):
        self.client.login(username='teniente', password='clave-segura-123')
        self.assertEqual(self.client.get(reverse('eliminar_gestion', args=[self.gestion.id])).status_code, 405)
        self.assertEqual(self.client.get(reverse('eliminar_esquema', args=[self.esquema.id])).status_code, 405)
        self.assertTrue(Gestion.objects.filter(id=self.gestion.id).exists())

        self.client.post(reverse('eliminar_gestion', args=[self.gestion.id]))
        self.assertFalse(Gestion.objects.filter(id=self.gestion.id).exists())

    def test_eliminar_protegido_muestra_mensaje_y_no_falla(self):
        puesto = Puesto.objects.create(esquema=self.esquema, nombre='Número 1', cargo='NUMERO', anio_requerido=2)
        guardia = GuardiaDia.objects.create(fecha='2026-03-10', esquema=self.esquema)
        DetalleGuardia.objects.create(guardia=guardia, puesto=puesto, estudiante=self.cadete)
        self.client.login(username='teniente', password='clave-segura-123')

        respuesta = self.client.post(reverse('eliminar_esquema', args=[self.esquema.id]), follow=True)
        self.assertContains(respuesta, 'No se puede eliminar el esquema')
        self.assertTrue(EsquemaGuardia.objects.filter(id=self.esquema.id).exists())

        respuesta = self.client.post(reverse('eliminar_estudiante', args=[self.cadete.id]), follow=True)
        self.assertContains(respuesta, 'tiene guardias')
        self.assertTrue(Estudiante.objects.filter(id=self.cadete.id).exists())


class CuentaEstudianteTests(TestCase):
    """Usuario = CI, clave inicial = primer apellido, cambio obligatorio y sin reinicios al editar"""

    def setUp(self):
        self.carrera = Carrera.objects.get(nombre='COMERCIAL')
        self.oficial = User.objects.create_superuser('Ernan', password='clave-segura-123')

    def crear_por_formulario(self, **datos):
        self.client.login(username='Ernan', password='clave-segura-123')
        base = {'ci': '7777777', 'nombres': 'ANA MARIA', 'apellidos': 'QUISPE ROJAS',
                'anio': 1, 'carrera': self.carrera.id, 'activo': 'on'}
        base.update(datos)
        return self.client.post(reverse('nuevo_estudiante'), base)

    def test_crear_estudiante_crea_cuenta_con_clave_inicial(self):
        self.crear_por_formulario()
        est = Estudiante.objects.get(ci='7777777')
        self.assertEqual(est.usuario.username, '7777777')
        self.assertTrue(est.usuario.check_password('quispe'))
        self.assertTrue(est.debe_cambiar_clave)
        self.assertFalse(est.usuario.is_staff)

    def test_formulario_exige_ci(self):
        respuesta = self.crear_por_formulario(ci='')
        self.assertContains(respuesta, 'El C.I. es obligatorio')
        self.assertFalse(Estudiante.objects.exists())

    def test_ci_no_puede_tomar_la_cuenta_del_oficial(self):
        respuesta = self.crear_por_formulario(ci='ernan')
        self.assertContains(respuesta, 'ya es el usuario de otra cuenta')
        self.oficial.refresh_from_db()
        self.assertTrue(self.oficial.check_password('clave-segura-123'))

    def test_editar_ficha_no_reinicia_la_clave(self):
        est = Estudiante.objects.create(ci='7777777', nombres='ANA', apellidos='QUISPE ROJAS', anio=1, carrera=self.carrera)
        est.usuario.set_password('mi-clave-nueva-2026')
        est.usuario.save()
        est.nombres = 'ANA MARIA'
        est.save()
        est.usuario.refresh_from_db()
        self.assertTrue(est.usuario.check_password('mi-clave-nueva-2026'))
        self.assertEqual(est.usuario.first_name, 'ANA MARIA')

    def test_sin_ci_no_hay_cuenta_y_se_crea_al_cargar_el_ci(self):
        est = Estudiante.objects.create(nombres='LUIS', apellidos='VARGAS', anio=2, carrera=self.carrera)
        self.assertIsNone(est.usuario)
        est.ci = '5555555'
        est.save()
        self.assertEqual(est.usuario.username, '5555555')

    def test_primer_ingreso_obliga_a_cambiar_la_clave(self):
        Estudiante.objects.create(ci='7777777', nombres='ANA', apellidos='QUISPE ROJAS', anio=1, carrera=self.carrera)
        self.assertTrue(self.client.login(username='7777777', password='quispe'))
        self.assertRedirects(self.client.get(reverse('home')), reverse('cambiar_clave'))
        self.assertRedirects(self.client.get(reverse('mis_solicitudes_ausencia')), reverse('cambiar_clave'))

        # No acepta volver a usar el apellido
        self.client.post(reverse('cambiar_clave'), {
            'old_password': 'quispe', 'new_password1': 'QUISPE', 'new_password2': 'QUISPE'})
        self.assertRedirects(self.client.get(reverse('home')), reverse('cambiar_clave'))

        respuesta = self.client.post(reverse('cambiar_clave'), {
            'old_password': 'quispe', 'new_password1': 'Guardia-Tropico-26', 'new_password2': 'Guardia-Tropico-26'})
        self.assertRedirects(respuesta, reverse('home'))
        self.assertEqual(self.client.get(reverse('home')).status_code, 200)  # Sigue con sesión
        self.assertFalse(Estudiante.objects.get(ci='7777777').debe_cambiar_clave)

    def test_oficial_restablece_la_clave(self):
        est = Estudiante.objects.create(ci='7777777', nombres='ANA', apellidos='QUISPE ROJAS', anio=1, carrera=self.carrera)
        est.usuario.set_password('olvidada-123456')
        est.usuario.save()
        Estudiante.objects.filter(pk=est.pk).update(debe_cambiar_clave=False)

        self.client.login(username='Ernan', password='clave-segura-123')
        self.client.post(reverse('restablecer_clave', args=[est.id]))
        est.refresh_from_db()
        est.usuario.refresh_from_db()
        self.assertTrue(est.usuario.check_password('quispe'))
        self.assertTrue(est.debe_cambiar_clave)

    def test_estudiante_inactivo_no_puede_entrar(self):
        est = Estudiante.objects.create(ci='7777777', nombres='ANA', apellidos='QUISPE ROJAS', anio=1, carrera=self.carrera)
        est.activo = False
        est.save()
        self.assertFalse(self.client.login(username='7777777', password='quispe'))

    def test_eliminar_estudiante_elimina_su_cuenta(self):
        est = Estudiante.objects.create(ci='7777777', nombres='ANA', apellidos='QUISPE ROJAS', anio=1, carrera=self.carrera)
        est.delete()
        self.assertFalse(User.objects.filter(username='7777777').exists())
        self.assertTrue(User.objects.filter(username='Ernan').exists())


class RodilloTests(TestCase):
    """Fila estricta por año: Sistemas -> Civil -> Comercial, sin repetir hasta completar la vuelta"""

    def setUp(self):
        from datetime import date
        from .models import EsquemaVigencia
        self.dia1 = date(2027, 3, 1)
        self.sis, self.civ, self.com = (Carrera.objects.get(nombre=n) for n in ('SISTEMAS', 'CIVIL', 'COMERCIAL'))
        # 4to año: 3 de Sistemas, 2 de Civil, 1 de Comercial (alfabéticamente Civil iría primero)
        self.s = [self.cadete('S' + l, self.sis, 4) for l in 'ABC']
        self.c = [self.cadete('C' + l, self.civ, 4) for l in 'AB']
        self.m = [self.cadete('MA', self.com, 4)]
        self.esquema = EsquemaGuardia.objects.create(nombre='Esquema T')
        self.comandante = Puesto.objects.create(esquema=self.esquema, nombre='Comandante', cargo='COMANDANTE', anio_requerido=4, orden=1)
        EsquemaVigencia.objects.create(esquema=self.esquema, fecha_desde=self.dia1)

    def cadete(self, apellido, carrera, anio):
        return Estudiante.objects.create(nombres='X', apellidos=apellido, anio=anio, carrera=carrera)

    def generar(self, desde, dias):
        from .rodillo import generar_rol
        return generar_rol(self.dia1 + timedelta(days=desde), self.dia1 + timedelta(days=desde + dias - 1))

    def secuencia(self, puesto=None):
        puesto = puesto or self.comandante
        return [d.estudiante.apellidos for d in
                DetalleGuardia.objects.filter(puesto=puesto).order_by('guardia__fecha')]

    def test_orden_sistemas_civil_comercial_y_vuelve_a_empezar(self):
        self.generar(0, 8)
        self.assertEqual(self.secuencia(), ['SA', 'SB', 'SC', 'CA', 'CB', 'MA', 'SA', 'SB'])

    def test_tildes_no_alteran_el_orden_alfabetico(self):
        from .rodillo import fila_del_anio
        self.cadete('ÁLVAREZ', self.sis, 3)
        self.cadete('BENÍTEZ', self.sis, 3)
        self.cadete('ZURITA', self.sis, 3)
        self.assertEqual([e.apellidos for e in fila_del_anio(3)], ['ÁLVAREZ', 'BENÍTEZ', 'ZURITA'])

    def test_continua_donde_quedo_entre_generaciones(self):
        self.generar(0, 2)
        self.generar(2, 5)
        self.assertEqual(self.secuencia(), ['SA', 'SB', 'SC', 'CA', 'CB', 'MA', 'SA'])

    def test_ausente_pierde_el_turno(self):
        AusenciaLicencia.objects.create(
            estudiante=self.s[1], tipo='SALUD', motivo='x', estado='APROBADA',
            fecha_inicio=self.dia1 + timedelta(days=1), fecha_fin=self.dia1 + timedelta(days=1),
        )
        resultado = self.generar(0, 7)
        # Día 2 le tocaba a SB (con licencia): va SC y SB recién vuelve en la siguiente vuelta
        self.assertEqual(self.secuencia(), ['SA', 'SC', 'CA', 'CB', 'MA', 'SA', 'SB'])
        self.assertEqual([e.apellidos for _, e in resultado.turnos_perdidos], ['SB'])

    def test_permuta_no_descuadra_la_fila(self):
        self.generar(0, 2)  # SA, SB
        detalle = DetalleGuardia.objects.get(guardia__fecha=self.dia1 + timedelta(days=1))
        detalle.estudiante = self.m[0]  # Reemplazo aprobado: MA cubre el día de SB
        detalle.save()
        self.generar(2, 1)
        self.assertEqual(self.secuencia()[-1], 'SC')  # La fila sigue después de SB, no de MA

    def test_dos_puestos_del_mismo_anio_toman_los_siguientes_sin_repetir(self):
        segundo = Puesto.objects.create(esquema=self.esquema, nombre='Número 4to', cargo='NUMERO', anio_requerido=4, orden=2)
        self.generar(0, 3)
        dias = [sorted(GuardiaDia.objects.get(fecha=self.dia1 + timedelta(days=i)).detalles.values_list('estudiante__apellidos', flat=True))
                for i in range(3)]
        self.assertEqual(dias, [['SA', 'SB'], ['CA', 'SC'], ['CB', 'MA']])

    def test_no_habilitado_se_salta(self):
        self.s[0].habilitado_desde = self.dia1 + timedelta(days=30)
        self.s[0].save()
        self.generar(0, 2)
        self.assertEqual(self.secuencia(), ['SB', 'SC'])

    def test_dias_ya_generados_no_se_modifican_y_la_fila_sigue(self):
        self.generar(0, 3)  # SA, SB, SC
        resultado = self.generar(0, 5)  # Los 3 primeros ya existen
        self.assertEqual(resultado.dias_ya_completos, 3)
        self.assertEqual(self.secuencia(), ['SA', 'SB', 'SC', 'CA', 'CB'])

    def test_esquema_sin_puestos_avisa_y_no_crea_dias_vacios(self):
        self.comandante.delete()
        resultado = self.generar(0, 3)
        self.assertEqual(resultado.esquemas_sin_puestos, {'Esquema T'})
        self.assertFalse(GuardiaDia.objects.exists())

    def test_vigencias_superpuestas_se_rechazan(self):
        from django.core.exceptions import ValidationError
        from .models import EsquemaVigencia
        otra = EsquemaVigencia(esquema=self.esquema, fecha_desde=self.dia1 + timedelta(days=10),
                               fecha_hasta=self.dia1 + timedelta(days=20))
        with self.assertRaises(ValidationError):
            otra.full_clean()

    def test_vista_rango_valida_fechas_y_genera(self):
        User.objects.create_superuser('Ernan', password='clave-segura-123')
        self.client.login(username='Ernan', password='clave-segura-123')
        url = reverse('generar_rango_guardias')
        self.client.post(url, {'fecha_inicio': 'mal', 'fecha_fin': '2027-03-02'})  # No debe dar error 500
        self.assertFalse(GuardiaDia.objects.exists())
        respuesta = self.client.post(url, {'fecha_inicio': '2027-03-01', 'fecha_fin': '2027-03-03'}, follow=True)
        self.assertContains(respuesta, '3 día(s) de guardia generados')
        self.assertEqual(self.secuencia(), ['SA', 'SB', 'SC'])


class PromocionYEsquemasTests(TestCase):

    def setUp(self):
        from datetime import date
        from .models import EsquemaVigencia
        self.dia1 = date(2027, 3, 1)
        self.sis = Carrera.objects.get(nombre='SISTEMAS')
        self.esquema = EsquemaGuardia.objects.create(nombre='Esquema A')
        self.puesto = Puesto.objects.create(esquema=self.esquema, nombre='Comandante', cargo='COMANDANTE', anio_requerido=4, orden=1)
        EsquemaVigencia.objects.create(esquema=self.esquema, fecha_desde=self.dia1)
        User.objects.create_superuser('Ernan', password='clave-segura-123')

    def cadete(self, apellido, anio):
        return Estudiante.objects.create(nombres='X', apellidos=apellido, anio=anio, carrera=self.sis)

    def test_promocion_de_anio_reinicia_la_fila(self):
        from .rodillo import generar_rol
        viejos = [self.cadete(a, 4) for a in ('VA', 'VB', 'VC')]
        nuevos = [self.cadete(a, 3) for a in ('NA', 'NB', 'NC')]
        generar_rol(self.dia1, self.dia1 + timedelta(days=1))  # VA, VB
        # Febrero: los de 4to egresan y los de 3ro pasan a 4to
        for e in viejos:
            e.activo = False
            e.save()
        for e in nuevos:
            e.anio = 4
            e.save()
        generar_rol(self.dia1 + timedelta(days=2), self.dia1 + timedelta(days=3))
        secuencia = list(DetalleGuardia.objects.order_by('guardia__fecha').values_list('estudiante__apellidos', flat=True))
        self.assertEqual(secuencia, ['VA', 'VB', 'NA', 'NB'])  # La fila nueva arranca desde el primero

    def datos_formulario(self, **extra):
        datos = {
            'nombre': 'Esquema B',
            'puestos-TOTAL_FORMS': '2', 'puestos-INITIAL_FORMS': '0',
            'puestos-0-orden': '1', 'puestos-0-nombre': 'Comandante', 'puestos-0-cargo': 'COMANDANTE', 'puestos-0-anio_requerido': '4',
            'puestos-1-orden': '2', 'puestos-1-nombre': 'Número 1ro', 'puestos-1-cargo': 'NUMERO', 'puestos-1-anio_requerido': '1',
            'vigencias-TOTAL_FORMS': '1', 'vigencias-INITIAL_FORMS': '0',
            'vigencias-0-fecha_desde': '2026-07-15', 'vigencias-0-fecha_hasta': '2027-02-14',
        }
        datos.update(extra)
        return datos

    def test_crear_esquema_con_puestos_y_vigencias(self):
        self.client.login(username='Ernan', password='clave-segura-123')
        respuesta = self.client.post(reverse('nuevo_esquema'), self.datos_formulario())
        self.assertRedirects(respuesta, reverse('lista_esquemas'))
        b = EsquemaGuardia.objects.get(nombre='Esquema B')
        self.assertEqual(sorted(b.puesto_set.values_list('anio_requerido', flat=True)), [1, 4])
        self.assertTrue(b.vigente_en(self.dia1 - timedelta(days=30)))
        self.assertContains(self.client.get(reverse('lista_esquemas')), 'Esquema B')

    def test_vigencia_superpuesta_con_otro_esquema_se_rechaza(self):
        self.client.login(username='Ernan', password='clave-segura-123')
        respuesta = self.client.post(reverse('nuevo_esquema'), self.datos_formulario(**{
            'vigencias-0-fecha_desde': '2027-04-01', 'vigencias-0-fecha_hasta': '2027-05-01'}))
        self.assertContains(respuesta, 'Se superpone con la vigencia de Esquema A')
        self.assertFalse(EsquemaGuardia.objects.filter(nombre='Esquema B').exists())

    def test_no_se_puede_quitar_un_puesto_ya_usado(self):
        from .rodillo import generar_rol
        self.cadete('VA', 4)
        generar_rol(self.dia1, self.dia1)
        vig = self.esquema.esquemavigencia_set.get()
        self.client.login(username='Ernan', password='clave-segura-123')
        respuesta = self.client.post(reverse('editar_esquema', args=[self.esquema.id]), {
            'nombre': 'Esquema A',
            'puestos-TOTAL_FORMS': '1', 'puestos-INITIAL_FORMS': '1',
            'puestos-0-id': self.puesto.id, 'puestos-0-esquema': self.esquema.id, 'puestos-0-orden': '1',
            'puestos-0-nombre': 'Comandante', 'puestos-0-cargo': 'COMANDANTE', 'puestos-0-anio_requerido': '4',
            'puestos-0-DELETE': 'on',
            'vigencias-TOTAL_FORMS': '1', 'vigencias-INITIAL_FORMS': '1',
            'vigencias-0-id': vig.id, 'vigencias-0-esquema': self.esquema.id, 'vigencias-0-fecha_desde': '2027-03-01',
        })
        self.assertContains(respuesta, 'ya se usó en guardias generadas')
        self.assertTrue(Puesto.objects.filter(id=self.puesto.id).exists())


class PromocionAnualTests(TestCase):

    def setUp(self):
        self.sis = Carrera.objects.get(nombre='SISTEMAS')
        self.cadetes = {
            anio: Estudiante.objects.create(ci=f'10{anio}', nombres='X', apellidos=f'ANIO{anio} PEREZ', anio=anio, carrera=self.sis)
            for anio in (1, 2, 3, 4, 5)
        }
        self.repitente = Estudiante.objects.create(ci='999', nombres='R', apellidos='REPITE LOPEZ', anio=3, carrera=self.sis)
        self.baja = Estudiante.objects.create(ci='888', nombres='B', apellidos='BAJA SOLIZ', anio=2, carrera=self.sis, activo=False)
        User.objects.create_superuser('Ernan', password='clave-segura-123')
        self.client.login(username='Ernan', password='clave-segura-123')

    def anios(self):
        return {e.apellidos: (e.anio, e.activo, e.egresado) for e in Estudiante.objects.all()}

    def test_vista_previa_muestra_lo_que_va_a_pasar_sin_cambiar_nada(self):
        respuesta = self.client.get(reverse('promocion_anio'))
        self.assertContains(respuesta, 'Egresan')
        self.assertContains(respuesta, 'Pasan a 5to Año (sin guardia)')
        self.assertContains(respuesta, 'Pasan a 4to Año')
        self.assertEqual(Estudiante.objects.get(pk=self.cadetes[5].pk).anio, 5)

    def test_sin_confirmar_no_promueve(self):
        self.client.post(reverse('promocion_anio'), {})
        self.assertFalse(Estudiante.objects.filter(egresado=True).exists())

    def test_promueve_egresa_y_respeta_repitentes_y_bajas(self):
        self.client.post(reverse('promocion_anio'), {'confirmo': '1', 'repite': [self.repitente.id]})
        a = self.anios()
        self.assertEqual(a['ANIO1 PEREZ'], (2, True, False))
        self.assertEqual(a['ANIO2 PEREZ'], (3, True, False))
        self.assertEqual(a['ANIO3 PEREZ'], (4, True, False))
        self.assertEqual(a['ANIO4 PEREZ'], (5, True, False))   # Pasa a 5to: sigue activo
        self.assertEqual(a['ANIO5 PEREZ'], (5, False, True))   # Egresado
        self.assertEqual(a['REPITE LOPEZ'], (3, True, False))  # Repite
        self.assertEqual(a['BAJA SOLIZ'], (2, False, False))   # De baja: no cambia
        self.assertTrue(User.objects.get(username='104').is_active)   # 5to año puede entrar
        self.assertFalse(User.objects.get(username='105').is_active)  # Cuenta del egresado desactivada

    def test_deshacer_devuelve_todo_como_estaba(self):
        antes = self.anios()
        self.client.post(reverse('promocion_anio'), {'confirmo': '1'})
        from .models import PromocionAnual
        promocion = PromocionAnual.objects.get()
        self.client.post(reverse('deshacer_promocion', args=[promocion.id]))
        self.assertEqual(self.anios(), antes)
        self.assertTrue(User.objects.get(username='105').is_active)
        # No se puede deshacer dos veces
        self.client.post(reverse('deshacer_promocion', args=[promocion.id]))
        self.assertEqual(self.anios(), antes)

    def test_egresados_salen_de_la_lista_por_anio(self):
        self.client.post(reverse('promocion_anio'), {'confirmo': '1'})
        respuesta = self.client.get(reverse('lista_estudiantes'))
        self.assertContains(respuesta, 'Egresados (1)')

    def test_cadete_no_puede_promover(self):
        Estudiante.objects.update(debe_cambiar_clave=False)
        self.client.login(username='101', password='anio1')
        self.assertRedirects(self.client.post(reverse('promocion_anio'), {'confirmo': '1'}), reverse('home'))
        self.assertFalse(Estudiante.objects.filter(egresado=True).exists())


    def test_quinto_anio_no_entra_al_rodillo_ni_como_reemplazante(self):
        from datetime import date
        from .models import EsquemaVigencia
        from .rodillo import fila_del_anio, ANIOS
        self.assertNotIn(5, ANIOS)
        self.assertNotIn(self.cadetes[5], fila_del_anio(4))
        respuesta = self.client.get(reverse('gestion_permutas'))
        self.assertNotIn(self.cadetes[5], list(respuesta.context['form'].fields['reemplazante'].queryset))
        self.assertIn(self.cadetes[4], list(respuesta.context['form'].fields['reemplazante'].queryset))


class PermutasTests(TestCase):
    """A solicita -> B acepta -> oficial aprueba. El oficial registra directo y puede aprobar el mismo día."""

    def setUp(self):
        self.hoy = timezone.localdate()
        carrera = Carrera.objects.get(nombre='SISTEMAS')

        def crear(ci, apellido, anio):
            return Estudiante.objects.create(ci=ci, nombres='X', apellidos=f'{apellido} PRUEBA', anio=anio, carrera=carrera)

        self.a, self.b, self.c = crear('201', 'ALFA', 2), crear('202', 'BETA', 2), crear('203', 'GAMA', 2)
        self.x = crear('301', 'TERCERO', 3)
        Estudiante.objects.update(debe_cambiar_clave=False)
        self.esquema = EsquemaGuardia.objects.create(nombre='Esquema B')
        self.p2 = Puesto.objects.create(esquema=self.esquema, nombre='Guardia 2do', cargo='NUMERO', anio_requerido=2, orden=3)
        self.p3 = Puesto.objects.create(esquema=self.esquema, nombre='Sargento', cargo='SARGENTO', anio_requerido=3, orden=2)
        self.det_a = self.asignar(2, self.p2, self.a)    # A: pasado mañana
        self.det_b = self.asignar(4, self.p2, self.b)    # B: en 4 días
        self.det_x = self.asignar(4, self.p3, self.x)    # X (3ro): en 4 días
        User.objects.create_superuser('Ernan', password='clave-segura-123')

    def asignar(self, dias, puesto, estudiante):
        guardia, _ = GuardiaDia.objects.get_or_create(fecha=self.hoy + timedelta(days=dias), defaults={'esquema': self.esquema})
        return DetalleGuardia.objects.create(guardia=guardia, puesto=puesto, estudiante=estudiante, estudiante_rodillo=estudiante)

    def como(self, usuario):
        self.client.logout()
        clave = 'clave-segura-123' if usuario == 'Ernan' else Estudiante.objects.get(ci=usuario).clave_inicial
        self.assertTrue(self.client.login(username=usuario, password=clave))

    def post(self, **datos):
        return self.client.post(reverse('gestion_permutas'), datos, follow=True)

    def solicitar_permuta(self, origen=None, destino=None):
        return self.post(accion='crear', tipo='PERMUTA', detalle_origen=(origen or self.det_a).id,
                         detalle_destino=(destino or self.det_b).id, motivo='Cruce con examen')

    def test_flujo_completo_de_permuta(self):
        from .models import Cambio
        self.como('201')
        self.solicitar_permuta()
        cambio = Cambio.objects.get()
        self.assertEqual(cambio.estado, 'ESPERA_CADETE')
        self.det_a.refresh_from_db()
        self.assertEqual(self.det_a.estudiante, self.a)  # Nada cambia hasta que se apruebe

        self.como('202')
        self.assertContains(self.client.get(reverse('home')), 'te pidieron cambio')
        self.post(accion='aceptar', cambio_id=cambio.id)
        cambio.refresh_from_db()
        self.assertEqual(cambio.estado, 'ESPERA_OFICIAL')

        self.como('Ernan')
        self.assertContains(self.client.get(reverse('home')), 'por aprobar')
        self.post(accion='aprobar', cambio_id=cambio.id)
        cambio.refresh_from_db()
        self.det_a.refresh_from_db()
        self.det_b.refresh_from_db()
        self.assertEqual(cambio.estado, 'APROBADO')
        self.assertEqual((self.det_a.estudiante, self.det_b.estudiante), (self.b, self.a))
        # El rodillo sigue sabiendo a quién le tocaba originalmente
        self.assertEqual((self.det_a.estudiante_rodillo, self.det_b.estudiante_rodillo), (self.a, self.b))

    def test_oficial_no_aprueba_sin_que_el_cadete_acepte(self):
        from .models import Cambio
        self.como('201')
        self.solicitar_permuta()
        self.como('Ernan')
        respuesta = self.post(accion='aprobar', cambio_id=Cambio.objects.get().id)
        self.assertContains(respuesta, 'no está esperando la aprobación del oficial')
        self.det_a.refresh_from_db()
        self.assertEqual(self.det_a.estudiante, self.a)

    def test_solo_el_cadete_destino_puede_responder(self):
        from .models import Cambio
        self.como('201')
        self.solicitar_permuta()
        self.como('203')  # GAMA no es parte de la permuta
        respuesta = self.client.post(reverse('gestion_permutas'), {'accion': 'aceptar', 'cambio_id': Cambio.objects.get().id})
        self.assertEqual(respuesta.status_code, 404)

    def test_solo_permuta_con_su_mismo_anio(self):
        from .models import Cambio
        from .permutas import CambioInvalido, validar
        with self.assertRaisesMessage(CambioInvalido, 'Solo se puede permutar con guardias de 2° año'):
            validar('PERMUTA', self.det_a, self.det_x)
        self.como('201')
        self.solicitar_permuta(destino=self.det_x)  # Ni siquiera aparece en la lista del cadete
        self.assertFalse(Cambio.objects.exists())

    def test_reemplazante_ocupado_con_licencia_o_de_otro_anio(self):
        from .permutas import CambioInvalido, validar
        otro_p2 = Puesto.objects.create(esquema=self.esquema, nombre='Guardia 2do B', cargo='NUMERO', anio_requerido=2, orden=4)
        self.asignar(2, otro_p2, self.c)  # GAMA ya está el día de A
        with self.assertRaisesMessage(CambioInvalido, 'ya tiene un puesto'):
            validar('REEMPLAZO', self.det_a, reemplazante=self.c)
        AusenciaLicencia.objects.create(estudiante=self.b, tipo='SALUD', motivo='x', estado='APROBADA',
                                        fecha_inicio=self.det_a.guardia.fecha, fecha_fin=self.det_a.guardia.fecha)
        with self.assertRaisesMessage(CambioInvalido, 'tiene licencia'):
            validar('REEMPLAZO', self.det_a, reemplazante=self.b)
        with self.assertRaisesMessage(CambioInvalido, 'cadete activo de 2° año'):
            validar('REEMPLAZO', self.det_a, reemplazante=self.x)

    def test_cadete_no_pide_cambios_para_hoy_pero_el_oficial_si(self):
        from .models import Cambio
        hoy_a = self.asignar(0, self.p2, self.a)
        self.como('201')
        self.post(accion='crear', tipo='REEMPLAZO', detalle_origen=hoy_a.id, reemplazante=self.c.id, motivo='x')
        self.assertFalse(Cambio.objects.exists())

        self.como('Ernan')
        respuesta = self.post(accion='crear', tipo='REEMPLAZO', detalle_origen=hoy_a.id, reemplazante=self.c.id, motivo='Fuerza mayor')
        self.assertContains(respuesta, 'registrada y aplicada')
        hoy_a.refresh_from_db()
        self.assertEqual(hoy_a.estudiante, self.c)
        self.assertEqual(Cambio.objects.get().estado, 'APROBADO')

    def test_oficial_aprueba_el_mismo_dia_de_la_guardia(self):
        from .models import Cambio
        hoy_a = self.asignar(0, self.p2, self.a)
        cambio = Cambio.objects.create(tipo='REEMPLAZO', detalle_origen=hoy_a, estudiante_origen=self.a,
                                       estudiante_destino=self.c, motivo='x', estado='ESPERA_OFICIAL')
        self.como('Ernan')
        self.post(accion='aprobar', cambio_id=cambio.id)
        cambio.refresh_from_db()
        self.assertEqual(cambio.estado, 'APROBADO')

    def test_vencimiento(self):
        from .models import Cambio
        from .permutas import vencer_pendientes
        hoy_a = self.asignar(0, self.p2, self.a)
        ayer_b = self.asignar(-1, self.p2, self.b)
        espera_cadete_hoy = Cambio.objects.create(tipo='REEMPLAZO', detalle_origen=hoy_a, estudiante_origen=self.a,
                                                  estudiante_destino=self.c, motivo='x', estado='ESPERA_CADETE')
        espera_oficial_futura = Cambio.objects.create(tipo='REEMPLAZO', detalle_origen=self.det_a, estudiante_origen=self.a,
                                                      estudiante_destino=self.c, motivo='x', estado='ESPERA_OFICIAL')
        espera_oficial_hoy = Cambio.objects.create(tipo='REEMPLAZO', detalle_origen=hoy_a, estudiante_origen=self.a,
                                                   estudiante_destino=self.c, motivo='x', estado='ESPERA_OFICIAL')
        espera_oficial_ayer = Cambio.objects.create(tipo='REEMPLAZO', detalle_origen=ayer_b, estudiante_origen=self.b,
                                                    estudiante_destino=self.c, motivo='x', estado='ESPERA_OFICIAL')
        vencer_pendientes()
        estados = {c.pk: c.estado for c in Cambio.objects.all()}
        self.assertEqual(estados[espera_cadete_hoy.pk], 'VENCIDO')            # B ya no puede aceptar hoy
        self.assertEqual(estados[espera_oficial_futura.pk], 'ESPERA_OFICIAL')
        self.assertEqual(estados[espera_oficial_hoy.pk], 'ESPERA_OFICIAL')    # El oficial aún puede hoy
        self.assertEqual(estados[espera_oficial_ayer.pk], 'VENCIDO')          # Ya pasó la guardia

    def test_no_permite_dos_solicitudes_abiertas_sobre_la_misma_guardia(self):
        from .models import Cambio
        self.como('201')
        self.solicitar_permuta()
        respuesta = self.post(accion='crear', tipo='REEMPLAZO', detalle_origen=self.det_a.id, reemplazante=self.c.id, motivo='x')
        self.assertContains(respuesta, 'Ya existe una solicitud de cambio abierta')
        self.assertEqual(Cambio.objects.count(), 1)

    def test_solicitante_puede_cancelar(self):
        from .models import Cambio
        self.como('201')
        self.solicitar_permuta()
        cambio = Cambio.objects.get()
        self.post(accion='cancelar', cambio_id=cambio.id)
        cambio.refresh_from_db()
        self.assertEqual(cambio.estado, 'CANCELADO')

    def test_si_la_guardia_cambio_no_se_aplica(self):
        from .models import Cambio
        self.como('201')
        self.solicitar_permuta()
        cambio = Cambio.objects.get()
        self.como('202')
        self.post(accion='aceptar', cambio_id=cambio.id)
        DetalleGuardia.objects.filter(pk=self.det_b.pk).update(estudiante=self.c)  # Otro cambio manual entretanto
        self.como('Ernan')
        respuesta = self.post(accion='aprobar', cambio_id=cambio.id)
        self.assertContains(respuesta, 'Las guardias cambiaron')
        self.det_a.refresh_from_db()
        self.assertEqual(self.det_a.estudiante, self.a)

    def test_reemplazo_limpia_la_licencia_del_cadete_anterior(self):
        ausencia = AusenciaLicencia.objects.create(estudiante=self.a, tipo='SALUD', motivo='x', estado='APROBADA',
                                                   fecha_inicio=self.det_a.guardia.fecha, fecha_fin=self.det_a.guardia.fecha)
        ausencia.aplicar_a_guardias(None)
        self.como('Ernan')
        self.post(accion='crear', tipo='REEMPLAZO', detalle_origen=self.det_a.id, reemplazante=self.c.id, motivo='Cubre licencia')
        self.det_a.refresh_from_db()
        self.assertEqual((self.det_a.estudiante, self.det_a.asistencia, self.det_a.ausencia), (self.c, 'PENDIENTE', None))

    def test_rechazo_del_oficial_exige_motivo(self):
        from .models import Cambio
        self.como('201')
        self.solicitar_permuta()
        cambio = Cambio.objects.get()
        self.como('202')
        self.post(accion='aceptar', cambio_id=cambio.id)
        self.como('Ernan')
        self.post(accion='rechazar', cambio_id=cambio.id)
        cambio.refresh_from_db()
        self.assertEqual(cambio.estado, 'ESPERA_OFICIAL')
        self.post(accion='rechazar', cambio_id=cambio.id, observacion='Sin justificación')
        cambio.refresh_from_db()
        self.assertEqual(cambio.estado, 'RECHAZADO')

    def test_paginas_cargan_para_cadete_y_oficial(self):
        self.como('201')
        respuesta = self.client.get(reverse('gestion_permutas'))
        self.assertContains(respuesta, 'Guardia 2do (2° año)')  # El puesto ya no sale vacío
        self.assertNotContains(respuesta, 'TERCERO')            # No ve cadetes de otro año
        self.como('Ernan')
        self.assertContains(self.client.get(reverse('gestion_permutas')), 'Por aprobar')


class InicioTests(TestCase):
    """El inicio muestra cualquier esquema, solo el mes actual y con pocas consultas"""

    def setUp(self):
        from .models import EsquemaVigencia
        from .rodillo import generar_rol
        self.hoy = timezone.localdate()
        sis = Carrera.objects.get(nombre='SISTEMAS')
        for anio, cantidad in ((4, 3), (3, 3), (2, 6)):
            for i in range(cantidad):
                Estudiante.objects.create(nombres='X', apellidos=f'A{anio}N{i} PRUEBA', anio=anio, carrera=sis)
        # Esquema A: Comandante, Sargento y 4 de 2do año (sin 1er año)
        a = EsquemaGuardia.objects.create(nombre='Esquema A')
        Puesto.objects.create(esquema=a, nombre='Comandante de Guardia', cargo='COMANDANTE', anio_requerido=4, orden=1)
        Puesto.objects.create(esquema=a, nombre='Sargento de Guardia', cargo='SARGENTO', anio_requerido=3, orden=2)
        for i in range(1, 5):
            Puesto.objects.create(esquema=a, nombre=f'Guardia 2do Año - {i}', cargo='NUMERO', anio_requerido=2, orden=i + 2)
        EsquemaVigencia.objects.create(esquema=a, fecha_desde=self.hoy - timedelta(days=40))
        generar_rol(self.hoy - timedelta(days=35), self.hoy + timedelta(days=35))
        User.objects.create_superuser('Ernan', password='clave-segura-123')
        self.client.login(username='Ernan', password='clave-segura-123')

    def test_guardia_de_hoy_muestra_los_cuatro_de_segundo(self):
        respuesta = self.client.get(reverse('home'))
        guardia = respuesta.context['guardia_hoy']
        self.assertEqual(len(guardia.numeros), 4)
        self.assertTrue(all(d.puesto.anio_requerido == 2 for d in guardia.numeros))
        self.assertContains(respuesta, 'Guardia 2do Año - 4 (2° Año)')
        self.assertEqual(guardia.comandante.puesto.anio_requerido, 4)

    def test_rol_del_mes_solo_trae_el_mes_actual(self):
        fechas = [g.fecha for g in self.client.get(reverse('home')).context['guardias_mes']]
        self.assertTrue(fechas)
        self.assertTrue(all(f.month == self.hoy.month and f.year == self.hoy.year for f in fechas))

    def test_consultas_no_crecen_con_la_cantidad_de_dias(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        with CaptureQueriesContext(connection) as consultas:
            self.client.get(reverse('home'))
        self.assertLess(len(consultas), 30)  # Antes eran ~10 por cada día del mes

    def test_zona_horaria_bolivia(self):
        from django.conf import settings
        self.assertEqual(settings.TIME_ZONE, 'America/La_Paz')
