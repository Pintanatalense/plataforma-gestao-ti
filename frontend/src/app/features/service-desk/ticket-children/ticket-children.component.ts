import { ChangeDetectorRef, Component, EventEmitter, Input, OnChanges, Output, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { RouterModule } from '@angular/router';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatTooltipModule } from '@angular/material/tooltip';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';

import {
  ChildTicketSpec,
  ChildTicketSummary,
  ChildrenProgress,
  STATUS_LABELS,
  Ticket,
  TicketCategory,
  TicketService,
  newIdempotencyKey
} from '../ticket.service';
import { apiErrorMessage } from '../../../core/http/api-error';

type Action = { kind: 'cancel' | 'dispense' | 'require' | 'replace'; child: ChildTicketSummary };

/**
 * Subchamados de um chamado principal (ADR-026): progresso, resumo de cada etapa e as ações que o backend autoriza.
 * O resumo não traz descrição nem conversa: o detalhe de cada subchamado é do setor dele.
 */
@Component({
  selector: 'app-ticket-children',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterModule, MatButtonModule, MatIconModule, MatTooltipModule, MatSnackBarModule],
  template: `
    <section class="children-card" data-testid="ticket-children">
      <header class="children-header">
        <div>
          <h3><mat-icon>account_tree</mat-icon> Subchamados</h3>
          <p class="progress-line" *ngIf="progress && progress.total > 0" data-testid="children-progress">
            {{ progress.done }} de {{ progress.total }} concluído(s)
            <span *ngIf="progress.canceled"> • {{ progress.canceled }} cancelado(s)</span>
            <span class="pending" *ngIf="progress.required_pending"> • {{ progress.required_pending }} etapa(s) obrigatória(s) pendente(s)</span>
            <span class="late" *ngIf="progress.steps_overdue"> • {{ progress.steps_overdue }} etapa(s) obrigatória(s) atrasada(s)</span>
            <span class="late" *ngIf="progress.process_overdue"> • prazo do processo vencido</span>
          </p>
          <p class="progress-line" *ngIf="!progress || progress.total === 0">Nenhum subchamado ainda.</p>
        </div>
        <button mat-stroked-button color="primary" type="button" *ngIf="canAdd" (click)="startAdd()" data-testid="add-children">
          <mat-icon>add</mat-icon> Incluir subchamados
        </button>
      </header>

      <div class="load-error" *ngIf="loadError" role="alert">{{ loadError }}</div>

      <table class="children-table" *ngIf="children.length > 0">
        <thead>
          <tr>
            <th>Etapa</th><th>Setor</th><th>Situação</th><th>Responsável</th><th>Prazo</th><th></th>
          </tr>
        </thead>
        <tbody>
          <tr *ngFor="let c of children" [class.canceled]="c.status === 'CANCELED'" data-testid="child-row">
            <td>
              <a [routerLink]="['/service-desk', c.id]">#{{ c.id.slice(0, 8) }} {{ c.title }}</a>
              <span class="tag" *ngIf="!c.is_required">não obrigatória</span>
              <span class="tag" *ngIf="c.replaced_by_ticket_id">substituída por #{{ c.replaced_by_ticket_id.slice(0, 8) }}</span>
              <span class="tag" *ngIf="c.replaces_ticket_id">substitui #{{ c.replaces_ticket_id.slice(0, 8) }}</span>
              <div class="muted">{{ c.category_name || 'Sem categoria' }}</div>
            </td>
            <td>{{ c.responsible_sector_name || '-' }}</td>
            <td>{{ statusLabel(c.status) }}</td>
            <td>{{ c.assignee_name || 'Aguardando' }}</td>
            <td>
              <span *ngIf="c.resolution_due_at">{{ c.resolution_due_at | date:'dd/MM HH:mm' }}</span>
              <span class="late" *ngIf="c.overdue"> atrasado</span>
              <span class="risk" *ngIf="!c.overdue && c.at_risk"> em risco</span>
            </td>
            <td class="actions">
              <ng-container *ngIf="canManage && parentOpen">
                <button mat-icon-button type="button" *ngIf="isActive(c)" (click)="start('cancel', c)"
                        matTooltip="Cancelar etapa (com justificativa)"><mat-icon>block</mat-icon></button>
                <button mat-icon-button type="button" *ngIf="c.is_required && c.status !== 'CANCELED'" (click)="start('dispense', c)"
                        matTooltip="Tornar não obrigatória"><mat-icon>remove_circle_outline</mat-icon></button>
                <button mat-icon-button type="button" *ngIf="!c.is_required && isActive(c)" (click)="start('require', c)"
                        matTooltip="Tornar obrigatória"><mat-icon>add_circle_outline</mat-icon></button>
                <button mat-icon-button type="button" *ngIf="c.status === 'CANCELED' && !c.replaced_by_ticket_id"
                        (click)="start('replace', c)" matTooltip="Substituir por outra etapa"><mat-icon>swap_horiz</mat-icon></button>
              </ng-container>
            </td>
          </tr>
        </tbody>
      </table>

      <!-- Ação com justificativa -->
      <div class="inline-form" *ngIf="action" data-testid="child-action-form">
        <h4>{{ actionTitle() }}: #{{ action.child.id.slice(0, 8) }} {{ action.child.title }}</h4>
        <ng-container *ngIf="action.kind === 'replace'">
          <ng-container *ngTemplateOutlet="specFields; context: { $implicit: replacement }"></ng-container>
        </ng-container>
        <label class="field">Justificativa (mínimo 10 caracteres)
          <textarea rows="2" [(ngModel)]="reason" name="reason" data-testid="child-action-reason"></textarea>
        </label>
        <div class="form-actions">
          <button mat-button type="button" (click)="action = null">Voltar</button>
          <button mat-flat-button color="primary" type="button" [disabled]="busy || reason.trim().length < 10"
                  (click)="confirmAction()" data-testid="child-action-confirm">Confirmar</button>
        </div>
      </div>

      <!-- Inclusão de subchamados -->
      <div class="inline-form" *ngIf="adding" data-testid="add-children-form">
        <h4>Incluir subchamados</h4>
        <div class="spec-row" *ngFor="let spec of newSpecs; let i = index">
          <ng-container *ngTemplateOutlet="specFields; context: { $implicit: spec }"></ng-container>
          <button mat-icon-button type="button" (click)="newSpecs.splice(i, 1)" *ngIf="newSpecs.length > 1"
                  matTooltip="Remover linha"><mat-icon>close</mat-icon></button>
        </div>
        <button mat-button type="button" (click)="newSpecs.push(emptySpec())"><mat-icon>add</mat-icon> Outra etapa</button>
        <div class="form-actions">
          <button mat-button type="button" (click)="adding = false">Voltar</button>
          <button mat-flat-button color="primary" type="button" [disabled]="busy || !specsValid(newSpecs)"
                  (click)="confirmAdd()" data-testid="add-children-confirm">Incluir</button>
        </div>
      </div>

      <ng-template #specFields let-spec>
        <div class="spec-fields">
          <label class="field">Categoria
            <select [(ngModel)]="spec.category_id" name="category">
              <option value="">Escolha…</option>
              <option *ngFor="let cat of categories" [value]="cat.id">{{ cat.name }}</option>
            </select>
          </label>
          <label class="field">Título <input [(ngModel)]="spec.title" name="title" maxlength="255"></label>
          <label class="field wide">Descrição <input [(ngModel)]="spec.description" name="description"></label>
          <label class="check"><input type="checkbox" [(ngModel)]="spec.is_required" name="required"> Obrigatória</label>
        </div>
      </ng-template>
    </section>
  `,
  styles: [`
    .children-card { margin: 16px 0; padding: 16px; border-radius: 12px; border: 1px solid var(--mat-sys-outline-variant);
      background: var(--mat-sys-surface-container-lowest); }
    .children-header { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; flex-wrap: wrap; }
    .children-header h3 { display: flex; align-items: center; gap: 6px; margin: 0; font-size: 16px; }
    .progress-line { margin: 4px 0 0; font-size: 13px; color: var(--mat-sys-on-surface-variant); }
    .pending { color: #b45309; }
    .late { color: #b91c1c; font-weight: 600; }
    .risk { color: #b45309; }
    .load-error { margin-top: 8px; color: #991b1b; }
    .children-table { width: 100%; border-collapse: collapse; margin-top: 12px; font-size: 13px; }
    .children-table th { text-align: left; font-weight: 600; padding: 6px; border-bottom: 1px solid var(--mat-sys-outline-variant); }
    .children-table td { padding: 6px; border-bottom: 1px solid var(--mat-sys-outline-variant); vertical-align: top; }
    .children-table tr.canceled td { opacity: 0.6; }
    .tag { display: inline-block; margin-left: 6px; padding: 0 6px; border-radius: 10px; font-size: 11px;
      background: var(--mat-sys-surface-container); }
    .muted { font-size: 12px; color: var(--mat-sys-on-surface-variant); }
    .actions { white-space: nowrap; text-align: right; }
    .inline-form { margin-top: 12px; padding: 12px; border-radius: 8px; background: var(--mat-sys-surface-container); }
    .inline-form h4 { margin: 0 0 8px; font-size: 14px; }
    .spec-row { display: flex; align-items: flex-end; gap: 8px; }
    .spec-fields { display: flex; flex-wrap: wrap; gap: 8px; align-items: flex-end; margin-bottom: 8px; flex: 1; }
    .field { display: flex; flex-direction: column; font-size: 12px; gap: 2px; min-width: 160px; }
    .field.wide { flex: 1 1 240px; }
    .field input, .field select, .field textarea { font: inherit; padding: 6px; border-radius: 6px;
      border: 1px solid var(--mat-sys-outline-variant); background: var(--mat-sys-surface); color: var(--mat-sys-on-surface); }
    .check { display: inline-flex; align-items: center; gap: 4px; font-size: 13px; }
    .form-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 8px; }
  `]
})
export class TicketChildrenComponent implements OnChanges {
  private ticketService = inject(TicketService);
  private snackBar = inject(MatSnackBar);
  private cdr = inject(ChangeDetectorRef);

  @Input({ required: true }) ticket!: Ticket;
  @Input() categories: TicketCategory[] = [];
  /** Solicitante, quem abriu ou atendente do setor do principal: incluem subchamados. */
  @Input() canAdd = false;
  /** Atendente do setor do principal: cancela, dispensa e substitui etapas. */
  @Input() canManage = false;
  /** Avisa a tela de detalhe para recarregar o principal (progresso e histórico). */
  @Output() changed = new EventEmitter<void>();

  children: ChildTicketSummary[] = [];
  progress: ChildrenProgress | null = null;
  loadError: string | null = null;
  busy = false;

  adding = false;
  newSpecs: ChildTicketSpec[] = [];
  private addKey = '';

  action: Action | null = null;
  reason = '';
  replacement: ChildTicketSpec = this.emptySpec();

  get parentOpen(): boolean {
    return !['RESOLVED', 'CLOSED'].includes(this.ticket?.status);
  }

  ngOnChanges(): void {
    this.load();
  }

  load(): void {
    if (!this.ticket) return;
    this.ticketService.getChildren(this.ticket.id).subscribe({
      next: (overview) => {
        this.children = overview.children;
        this.progress = overview.progress;
        this.loadError = null;
        this.cdr.markForCheck();
      },
      error: (err) => {
        this.loadError = apiErrorMessage(err, 'Não foi possível carregar os subchamados.');
        this.cdr.markForCheck();
      }
    });
  }

  statusLabel(status: string): string {
    return STATUS_LABELS[status] || status;
  }

  isActive(c: ChildTicketSummary): boolean {
    return !['RESOLVED', 'CLOSED', 'CANCELED'].includes(c.status);
  }

  emptySpec(): ChildTicketSpec {
    return { category_id: '', title: '', description: '', is_required: true };
  }

  specsValid(specs: ChildTicketSpec[]): boolean {
    return specs.length > 0 && specs.every((s) => s.category_id && s.title.trim() && s.description.trim());
  }

  startAdd(): void {
    this.action = null;
    this.adding = true;
    this.newSpecs = [this.emptySpec()];
    this.addKey = newIdempotencyKey();  // a mesma chave nas novas tentativas desta inclusão
  }

  confirmAdd(): void {
    this.busy = true;
    this.ticketService.addChildren(this.ticket.id, this.newSpecs, this.addKey).subscribe({
      next: (created) => {
        this.busy = false;
        this.adding = false;
        this.snackBar.open(`${created.length} subchamado(s) incluído(s).`, 'OK', { duration: 3500 });
        this.load();
        this.changed.emit();
      },
      error: (err) => this.fail(err, 'Não foi possível incluir os subchamados.')
    });
  }

  start(kind: Action['kind'], child: ChildTicketSummary): void {
    this.adding = false;
    this.action = { kind, child };
    this.reason = '';
    this.replacement = this.emptySpec();
  }

  actionTitle(): string {
    switch (this.action?.kind) {
      case 'cancel': return 'Cancelar etapa';
      case 'dispense': return 'Tornar não obrigatória';
      case 'require': return 'Tornar obrigatória';
      default: return 'Substituir etapa cancelada';
    }
  }

  confirmAction(): void {
    if (!this.action) return;
    const { kind, child } = this.action;
    const reason = this.reason.trim();
    if (kind === 'replace' && !this.specsValid([this.replacement])) {
      this.snackBar.open('Preencha categoria, título e descrição da etapa nova.', 'Fechar', { duration: 4000 });
      return;
    }
    const request =
      kind === 'cancel' ? this.ticketService.cancelChild(child.id, reason)
      : kind === 'replace' ? this.ticketService.replaceChild(child.id, reason, { ...this.replacement, is_required: true })
      : this.ticketService.setChildRequirement(child.id, kind === 'require', reason);
    this.busy = true;
    request.subscribe({
      next: () => {
        this.busy = false;
        this.action = null;
        this.snackBar.open('Etapa atualizada.', 'OK', { duration: 3000 });
        this.load();
        this.changed.emit();
      },
      error: (err) => this.fail(err, 'Não foi possível atualizar a etapa.')
    });
  }

  private fail(err: unknown, fallback: string): void {
    this.busy = false;
    this.snackBar.open(apiErrorMessage(err, fallback), 'Fechar', { duration: 6000 });
    this.cdr.markForCheck();
  }
}
