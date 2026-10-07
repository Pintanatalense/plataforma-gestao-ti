# ADR-003 — Arquivos Fora do Banco de Dados

**Status:** Aceito  
**Data:** 2026-10-02  

## Contexto

Anexos de chamados, termos de entrega e checklists precisam ser armazenados pelo sistema.

## Decisão

Arquivos serão armazenados no filesystem (volume Docker), não como BLOB no banco. O banco armazenará metadados: nome original, nome armazenado (UUID), caminho, MIME type, tamanho, hash SHA-256, usuário, data e visibilidade.

## Justificativa

- Evita bloat do banco de dados
- Facilita backup diferenciado (dump do banco + rsync de arquivos)
- Permite migração futura para object storage (S3, MinIO)
- Limite de 100 MB por arquivo torna BLOB impraticável

## Consequências

- Necessidade de gerenciar volume Docker para persistência
- Backup precisa incluir tanto banco quanto filesystem
- Nomes de arquivo armazenados como UUID para evitar colisão
