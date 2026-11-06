import { ChangeDetectorRef, Component, OnInit, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatTooltipModule } from '@angular/material/tooltip';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';

import { TicketCategory, TicketService, TicketTemplate, TicketTemplateItem } from '../ticket.service';
import { apiErrorMessage } from '../../../core/http/api-error';

type Draft = { id: string | null; name: string; description: string; is_active: boolean; items: TicketTemplateItem[] };

/**
 * Modelos de atendimento (ADR-026): listas de subchamados que a abertura de chamado usa para pré-preencher as etapas.
 * O modelo não cria nada sozinho; cada item passa pelas regras de sempre quando o chamado é aberto.
 */
@Component({
  selector: 'app-ticket-templates',
  standalone: true,
  imports: [CommonModule, FormsModule, MatButtonModule, MatIconModule, MatTooltipModule, MatSnackBarModule],
  template: `
    <div class="page">
      <header class="page-header">
        <div>
          <h1>Modelos de Atendimento</h1>
          <p class="subtitle">Listas reutilizáveis de subchamados. Na abertura de um chamado, "Usar modelo" preenche as etapas, que podem ser editadas antes de abrir.</p>
        </div>
        <button mat-flat-button color="primary" type="button" (click)="newDraft()" data-testid="new-template">
          <mat-icon>add</mat-icon> Novo modelo
        </button>
      </header>

      <label class="show-inactive">
        <input type="checkbox" [(ngModel)]="includeInactive" (change)="load()"> Mostrar desativados
      </label>

      <div class="load-error" *ngIf="loadError" role="alert">{{ loadError }}</div>

      <table class="templates-table" *ngIf="templates.length > 0">
        <thead><tr><th>Nome</th><th>Etapas</th><th>Situação</th><th></th></tr></thead>
        <tbody>
          <tr *ngFor="let tpl of templates" data-testid="template-row">
            <td><strong>{{ tpl.name }}</strong><div class="muted">{{ tpl.description }}</div></td>
            <td>{{ tpl.items.length }}</td>
            <td>{{ tpl.is_active ? 'Ativo' : 'Desativado' }}</td>
            <td class="actions">
              <button mat-icon-button type="button" (click)="edit(tpl)" matTooltip="Editar"><mat-icon>edit</mat-icon></button>
              <button mat-icon-button type="button" *ngIf="tpl.is_active" (click)="deactivate(tpl)" matTooltip="Desativar">
                <mat-icon>block</mat-icon>
              </button>
            </td>
          </tr>
        </tbody>
      </table>
      <p class="muted" *ngIf="templates.length === 0 && !loadError">Nenhum modelo cadastrado.</p>

      <section class="editor" *ngIf="draft" data-testid="template-editor">
        <h2>{{ draft.id ? 'Editar modelo' : 'Novo modelo' }}</h2>
        <label class="field">Nome <input [(ngModel)]="draft.name" maxlength="120" data-testid="template-name"></label>
        <label class="field">Descrição <input [(ngModel)]="draft.description"></label>
        <label class="check"><input type="checkbox" [(ngModel)]="draft.is_active"> Ativo</label>

        <h3>Etapas</h3>
        <div class="item-row" *ngFor="let item of draft.items; let i = index" data-testid="template-item">
          <label class="field">Categoria
            <select [(ngModel)]="item.category_id">
              <option value="">Escolha…</option>
              <option *ngFor="let cat of categories" [value]="cat.id">{{ cat.name }}</option>
            </select>
          </label>
          <label class="field">Título <input [(ngModel)]="item.title" maxlength="255"></label>
          <label class="field wide">Descrição <input [(ngModel)]="item.description"></label>
          <label class="check"><input type="checkbox" [(ngModel)]="item.is_required"> Obrigatória</label>
          <button mat-icon-button type="button" (click)="draft.items.splice(i, 1)" *ngIf="draft.items.length > 1"
                  matTooltip="Remover etapa"><mat-icon>close</mat-icon></button>
        </div>
        <button mat-button type="button" (click)="draft.items.push(emptyItem())"><mat-icon>add</mat-icon> Outra etapa</button>

        <div class="form-actions">
          <button mat-button type="button" (click)="draft = null">Cancelar</button>
          <button mat-flat-button color="primary" type="button" [disabled]="saving || !valid()" (click)="save()"
                  data-testid="save-template">Salvar</button>
        </div>
      </section>
    </div>
  `,
  styles: [`
    .page { padding: 24px; max-width: 1100px; }
    .page-header { display: flex; justify-content: space-between; align-items: flex-start; gap: 16px; flex-wrap: wrap; }
    .page-header h1 { margin: 0; }
    .subtitle, .muted { color: var(--mat-sys-on-surface-variant); font-size: 13px; }
    .show-inactive { display: inline-flex; align-items: center; gap: 6px; margin: 12px 0; font-size: 13px; }
    .load-error { color: #991b1b; }
    .templates-table { width: 100%; border-collapse: collapse; font-size: 14px; }
    .templates-table th, .templates-table td { text-align: left; padding: 8px; border-bottom: 1px solid var(--mat-sys-outline-variant); }
    .actions { text-align: right; white-space: nowrap; }
    .editor { margin-top: 24px; padding: 16px; border-radius: 12px; border: 1px solid var(--mat-sys-outline-variant); }
    .editor h2 { margin-top: 0; font-size: 18px; }
    .editor h3 { font-size: 15px; margin: 16px 0 8px; }
    .field { display: flex; flex-direction: column; gap: 2px; font-size: 12px; min-width: 180px; margin-bottom: 8px; }
    .field.wide { flex: 1 1 260px; }
    .field input, .field select { font: inherit; padding: 6px; border-radius: 6px; border: 1px solid var(--mat-sys-outline-variant);
      background: var(--mat-sys-surface); color: var(--mat-sys-on-surface); }
    .check { display: inline-flex; align-items: center; gap: 4px; font-size: 13px; }
    .item-row { display: flex; flex-wrap: wrap; gap: 8px; align-items: flex-end; }
    .form-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 12px; }
  `]
})
export class TicketTemplatesComponent implements OnInit {
  private ticketService = inject(TicketService);
  private snackBar = inject(MatSnackBar);
  private cdr = inject(ChangeDetectorRef);

  templates: TicketTemplate[] = [];
  categories: TicketCategory[] = [];
  includeInactive = false;
  loadError: string | null = null;
  draft: Draft | null = null;
  saving = false;

  ngOnInit(): void {
    this.ticketService.getCategories().subscribe({ next: (cats) => (this.categories = cats), error: () => {} });
    this.load();
  }

  load(): void {
    this.ticketService.listTemplates(this.includeInactive).subscribe({
      next: (templates) => {
        this.templates = templates;
        this.loadError = null;
        this.cdr.markForCheck();
      },
      error: (err) => {
        this.loadError = apiErrorMessage(err, 'Não foi possível carregar os modelos.');
        this.cdr.markForCheck();
      }
    });
  }

  emptyItem(): TicketTemplateItem {
    return { category_id: '', title: '', description: '', is_required: true };
  }

  newDraft(): void {
    this.draft = { id: null, name: '', description: '', is_active: true, items: [this.emptyItem()] };
  }

  edit(tpl: TicketTemplate): void {
    this.draft = {
      id: tpl.id,
      name: tpl.name,
      description: tpl.description || '',
      is_active: tpl.is_active,
      items: tpl.items.map((i) => ({
        category_id: i.category_id, responsible_sector_id: i.responsible_sector_id || null, title: i.title,
        description: i.description, default_custom_fields: i.default_custom_fields || {}, is_required: i.is_required
      }))
    };
  }

  valid(): boolean {
    return !!this.draft && !!this.draft.name.trim() && this.draft.items.length > 0
      && this.draft.items.every((i) => i.category_id && i.title.trim() && i.description.trim());
  }

  save(): void {
    if (!this.draft) return;
    const { id, ...body } = this.draft;
    const payload = { ...body, description: body.description || null };
    this.saving = true;
    const request = id ? this.ticketService.updateTemplate(id, payload) : this.ticketService.createTemplate(payload);
    request.subscribe({
      next: () => {
        this.saving = false;
        this.draft = null;
        this.snackBar.open('Modelo salvo.', 'OK', { duration: 3000 });
        this.load();
      },
      error: (err) => {
        this.saving = false;
        this.snackBar.open(apiErrorMessage(err, 'Não foi possível salvar o modelo.'), 'Fechar', { duration: 6000 });
        this.cdr.markForCheck();
      }
    });
  }

  deactivate(tpl: TicketTemplate): void {
    if (!confirm(`Desativar o modelo "${tpl.name}"? Os chamados já abertos com ele não mudam.`)) return;
    this.ticketService.deactivateTemplate(tpl.id).subscribe({
      next: () => {
        this.snackBar.open('Modelo desativado.', 'OK', { duration: 3000 });
        this.load();
      },
      error: (err) => this.snackBar.open(apiErrorMessage(err, 'Não foi possível desativar.'), 'Fechar', { duration: 6000 })
    });
  }
}
