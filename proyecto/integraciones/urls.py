from django.urls import path
from . import views


urlpatterns = [

    # -------------------------------
    # FUENTES DE LISTAS DE PRECIOS
    # -------------------------------

    path(
        "integraciones/listas-precios/",
        views.price_sources_list,
        name="price_sources_list",
    ),

    path(
        "integraciones/listas-precios/nueva/",
        views.price_source_create,
        name="price_source_create",
    ),

    path(
        "integraciones/listas-precios/<int:pk>/editar/",
        views.price_source_edit,
        name="price_source_edit",
    ),

    path(
        "integraciones/listas-precios/<int:pk>/activar/",
        views.price_source_toggle,
        name="price_source_toggle",
    ),

    path(
        "integraciones/listas-precios/<int:pk>/eliminar/",
        views.price_source_delete,
        name="price_source_delete",
    ),

    path(
        "integraciones/listas-precios/<int:pk>/sincronizar/",
        views.price_source_sync,
        name="price_source_sync",
    ),

    path(
        "integraciones/listas-precios/sincronizar-todas/",
        views.price_sources_sync_all,
        name="price_sources_sync_all",
    ),

    # -------------------------------
    # GESTIÓN DE CAMBIOS DE PRECIOS
    # -------------------------------

    path(
        "integraciones/cambios-doc-precios/",
        views.gestionar_cambios_doc_precios,
        name="gestionar_cambios_doc_precios",
    ),

    path(
        "integraciones/cambios-doc-precios/<int:source_id>/",
        views.gestionar_cambios_doc_precios,
        name="gestionar_cambios_doc_precios_source",
    ),

    # -------------------------------
    # DIAGNÓSTICO DE MATCH CON BD
    # -------------------------------

    path(
        "integraciones/diagnostico-match-lista/",
        views.diagnostico_match_lista,
        name="diagnostico_match_lista",
    ),

    path(
        "integraciones/diagnostico-match-lista/<int:source_id>/",
        views.diagnostico_match_lista,
        name="diagnostico_match_lista_source",
    ),

]