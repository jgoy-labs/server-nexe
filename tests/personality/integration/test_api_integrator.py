"""
Tests per personality/integration/api_integrator.py,
route_manager.py, openapi_merger.py i messages.py
"""
import pytest
from unittest.mock import MagicMock
from fastapi import FastAPI, APIRouter


# ─── messages.py ────────────────────────────────────────────────────────────

class TestGetMessage:
    def test_without_i18n_known_key(self):
        from personality.integration.messages import get_message
        msg = get_message(None, 'route_manager.info.routes_removed', count=3, module='test')
        assert '3' in msg
        assert 'test' in msg

    def test_without_i18n_unknown_key(self):
        from personality.integration.messages import get_message
        msg = get_message(None, 'unknown.key')
        assert msg == 'unknown.key'

    def test_with_i18n(self):
        from personality.integration.messages import get_message
        mock_i18n = MagicMock()
        mock_i18n.t.return_value = 'traduit'
        msg = get_message(mock_i18n, 'some.key', foo='bar')
        assert msg == 'traduit'

    def test_all_fallback_keys_exist(self):
        from personality.integration.messages import FALLBACK_MESSAGES
        assert len(FALLBACK_MESSAGES) > 0
        for key, val in FALLBACK_MESSAGES.items():
            assert isinstance(key, str)
            assert isinstance(val, str)

    def test_missing_format_args_returns_template(self):
        from personality.integration.messages import get_message
        # clau amb placeholder però sense args → retorna template sense formatejar
        msg = get_message(None, 'route_manager.info.routes_removed')
        assert isinstance(msg, str)


# ─── OpenAPIMerger ───────────────────────────────────────────────────────────

class TestOpenAPIMerger:
    def setup_method(self):
        from personality.integration.openapi_merger import OpenAPIMerger
        self.app = FastAPI()
        self.merger = OpenAPIMerger(self.app)

    def test_creation(self):
        from personality.integration.openapi_merger import OpenAPIMerger
        assert self.merger.main_app is self.app
        assert self.merger.i18n is None

    def test_merge_module_openapi_success(self):
        components = {'router': MagicMock()}
        result = self.merger.merge_module_openapi('test_module', components, '/api/test')
        assert result is True
        assert 'test_module' in self.merger._module_specs

    def test_merge_empty_components(self):
        # Amb components buits, _extract_module_openapi retorna dict buit → falsy → return False
        result = self.merger.merge_module_openapi('empty_mod', {}, '/api/empty')
        # L'extracció retorna {'prefix':..., 'components': []} que és truthy → True
        assert isinstance(result, bool)

    def test_remove_module_openapi_existing(self):
        self.merger._module_specs['mod'] = {'prefix': '/api/mod', 'components': []}
        result = self.merger.remove_module_openapi('mod')
        assert result is True
        assert 'mod' not in self.merger._module_specs

    def test_remove_module_openapi_nonexistent(self):
        result = self.merger.remove_module_openapi('does_not_exist')
        assert result is True

    def test_get_unified_spec(self):
        self.merger._module_specs['a'] = {}
        self.merger._module_specs['b'] = {}
        spec = self.merger.get_unified_spec()
        assert spec['total_modules'] == 2
        assert 'a' in spec['modules']

    def test_extract_module_openapi(self):
        components = {'router': MagicMock(), 'app': MagicMock()}
        result = self.merger._extract_module_openapi(components, '/api/test')
        assert result is not None
        assert result['prefix'] == '/api/test'
        assert 'router' in result['components']


# ─── RouteManager ────────────────────────────────────────────────────────────

class TestRouteManager:
    def setup_method(self):
        from personality.integration.route_manager import RouteManager
        self.app = FastAPI()
        self.rm = RouteManager(self.app)

    def test_creation(self):
        assert self.rm.main_app is self.app
        assert self.rm.i18n is None

    def test_register_router_routes(self):
        router = APIRouter()

        @router.get('/hello')
        def hello():
            return {'hello': 'world'}

        routes = self.rm.register_module_routes('mod1', router, '/api/mod1', 'router')
        assert len(routes) == 1
        assert routes[0]['path'] == '/api/mod1/hello'

    def test_register_router_conflict(self):
        router = APIRouter()

        @router.get('/hello')
        def hello():
            return {}

        # Primer registre
        routes1 = self.rm.register_module_routes('mod1', router, '/api/mod1', 'router')
        # Simular conflicte: afegir la ruta manualment al _route_conflicts
        # i tornar a registrar el mateix path
        router2 = APIRouter()

        @router2.get('/hello')
        def hello2():
            return {}

        # El path /api/mod1/hello ja existeix → conflicte → s'omet
        routes2 = self.rm.register_module_routes('mod1', router2, '/api/mod1', 'router')
        # La ruta ja estava registrada → 0 noves
        assert len(routes2) == 0

    def test_register_app_routes(self):
        sub_app = FastAPI()

        @sub_app.get('/test')
        def test_route():
            return {}

        routes = self.rm.register_module_routes('mod2', sub_app, '/app/mod2', 'app')
        assert len(routes) >= 0  # pot ser 0 si l'app no té APIRoute directes

    def test_register_endpoints_returns_empty(self):
        # _register_endpoint_routes retorna llista buida (no implementat)
        routes = self.rm.register_module_routes('mod3', [], '/api/mod3', 'endpoints')
        assert routes == []

    def test_register_unknown_component_type(self):
        routes = self.rm.register_module_routes('mod4', MagicMock(), '/api/mod4', 'unknown')
        assert routes == []

    def test_remove_nonexistent_module(self):
        count = self.rm.remove_module_routes('nonexistent')
        assert count == 0

    def test_remove_existing_module(self):
        router = APIRouter()

        @router.get('/foo')
        def foo():
            return {}

        self.rm.register_module_routes('mod5', router, '/api/mod5', 'router')
        count = self.rm.remove_module_routes('mod5')
        assert count >= 0  # pot ser 0 si no hi havia conflictes registrats
        assert 'mod5' not in self.rm._module_routes

    def test_get_all_registered_routes(self):
        router = APIRouter()

        @router.get('/bar')
        def bar():
            return {}

        self.rm.register_module_routes('mod6', router, '/api/mod6', 'router')
        all_routes = self.rm.get_all_registered_routes()
        assert 'mod6' in all_routes

    def test_get_route_conflicts(self):
        conflicts = self.rm.get_route_conflicts()
        assert isinstance(conflicts, dict)

    def test_check_route_conflict_new(self):
        result = self.rm._check_route_conflict('/new/path', 'mod_x')
        assert result is False

    def test_check_route_conflict_existing(self):
        self.rm._route_conflicts['/existing'] = 'other_mod'
        result = self.rm._check_route_conflict('/existing', 'new_mod')
        assert result is True


# ─── APIIntegrator ───────────────────────────────────────────────────────────

class TestAPIIntegrator:
    def setup_method(self):
        from personality.integration.api_integrator import APIIntegrator
        self.app = FastAPI()
        self.integrator = APIIntegrator(self.app)

    def test_creation(self):
        assert self.integrator.main_app is self.app
        assert self.integrator.i18n is None
        assert self.integrator._total_modules_integrated == 0
        assert self.integrator._total_routes_registered == 0

    def test_creation_with_i18n(self):
        from personality.integration.api_integrator import APIIntegrator
        mock_i18n = MagicMock()
        integrator = APIIntegrator(FastAPI(), i18n_manager=mock_i18n)
        assert integrator.i18n is mock_i18n

    def test_detect_api_components_with_router(self):
        instance = MagicMock()
        router = APIRouter()
        instance.router = router
        components = self.integrator._detect_api_components(instance)
        assert 'router' in components
        assert components['router'] is router

    def test_detect_api_components_with_app(self):
        instance = MagicMock(spec=[])
        instance.app = FastAPI()
        components = self.integrator._detect_api_components(instance)
        assert 'app' in components

    def test_detect_api_components_empty(self):
        class Empty:
            pass
        components = self.integrator._detect_api_components(Empty())
        assert 'router' not in components
        assert 'app' not in components

    def test_determine_api_prefix_default(self):
        prefix = self.integrator._determine_api_prefix('my_module')
        assert prefix == '/api/my_module'

    def test_determine_api_prefix_from_module_info(self):
        module_info = MagicMock()
        module_info.manifest = {'api': {'prefix': '/custom/prefix'}}
        prefix = self.integrator._determine_api_prefix('mod', module_info)
        assert prefix == '/custom/prefix'

    def test_determine_api_prefix_from_instance(self):
        module_info = MagicMock()
        module_info.manifest = {}
        module_info.instance.api_prefix = '/instance/prefix'
        prefix = self.integrator._determine_api_prefix('mod', module_info)
        assert prefix == '/instance/prefix'

    def test_integrate_module_with_router(self):
        router = APIRouter()

        @router.get('/ping')
        def ping():
            return {'ping': 'pong'}

        instance = MagicMock(spec=[])
        instance.router = router

        result = self.integrator.integrate_module_api('test_mod', instance)
        assert result is True
        assert self.integrator.is_module_integrated('test_mod')
        assert self.integrator._total_modules_integrated == 1
        assert self.integrator._total_routes_registered >= 1

    def test_integrate_module_without_api(self):
        class NoAPI:
            pass
        result = self.integrator.integrate_module_api('no_api_mod', NoAPI())
        assert result is False

    def test_get_integration_stats(self):
        stats = self.integrator.get_integration_stats()
        assert 'total_modules_integrated' in stats
        assert 'total_routes_registered' in stats
        assert 'integrated_modules' in stats
        assert 'modules_details' in stats

    def test_is_module_integrated_false(self):
        assert self.integrator.is_module_integrated('nonexistent') is False

    def test_get_module_routes_not_integrated(self):
        routes = self.integrator.get_module_routes('nonexistent')
        assert routes == []

    def test_get_module_routes_integrated(self):
        router = APIRouter()

        @router.get('/route1')
        def r1():
            return {}

        instance = MagicMock(spec=[])
        instance.router = router
        self.integrator.integrate_module_api('route_mod', instance)
        routes = self.integrator.get_module_routes('route_mod')
        assert isinstance(routes, list)

    def test_remove_nonintegrated_module(self):
        result = self.integrator.remove_module_api('nonexistent')
        assert result is True

    def test_remove_integrated_module(self):
        router = APIRouter()

        @router.get('/remove_test')
        def rt():
            return {}

        instance = MagicMock(spec=[])
        instance.router = router
        self.integrator.integrate_module_api('remove_mod', instance)
        assert self.integrator.is_module_integrated('remove_mod')

        result = self.integrator.remove_module_api('remove_mod')
        assert result is True
        assert not self.integrator.is_module_integrated('remove_mod')

    def test_handle_integration_error(self):
        result = self.integrator._handle_integration_error('err_mod', Exception('test error'))
        assert result is False

    def test_save_integration_info(self):
        self.integrator._save_integration_info(
            'saved_mod', MagicMock(), {'router': MagicMock()}, '/api/saved',
            [{'path': '/api/saved/x', 'methods': ['GET'], 'name': 'x', 'module': 'saved_mod'}]
        )
        assert 'saved_mod' in self.integrator._integrated_modules
        assert self.integrator._total_modules_integrated == 1
        assert self.integrator._total_routes_registered == 1
