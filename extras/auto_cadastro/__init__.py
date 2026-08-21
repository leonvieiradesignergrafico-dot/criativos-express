"""Auto-cadastro de produtos do Criativos Express (Fase 1).

Varre os anúncios+criativos de um cliente (via endpoint de leitura do Dashboard),
agrupa por página de destino = produto, e monta rascunhos em products/<cliente>/<produto>/
pra o Leon revisar. Read-only + escrita local. Nunca gasta dinheiro.
"""
