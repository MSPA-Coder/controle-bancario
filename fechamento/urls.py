"""URLs do Roteiro de fechamento (Movimentação > Importação)."""
from django.urls import path

from . import views

app_name = 'fechamento'

urlpatterns = [
    path('banking/closing/', views.painel_view, name='painel'),
    path('banking/closing/sources/', views.fontes_view, name='fontes'),
    path('banking/closing/sources/<int:account_id>/', views.salvar_fonte_view, name='salvar_fonte'),
    path('banking/closing/cuts/', views.cortes_view, name='cortes'),
    path('banking/closing/cuts/conclude/', views.concluir_corte_view, name='concluir_corte'),
    path('banking/closing/myprofit/', views.coleta_view, name='coleta'),
    path('banking/closing/duplicates/dismiss/', views.descartar_duplicata_view, name='descartar_duplicata'),
]
