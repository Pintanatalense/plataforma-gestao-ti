import { Component, computed, input } from '@angular/core';
import { DatePipe } from '@angular/common';
import { MatIconModule } from '@angular/material/icon';
import { MatTooltipModule } from '@angular/material/tooltip';

import { SlaInfo } from '../sla.service';

const STATE: Record<string, { label: string; icon: string; css: string }> = {
  RUNNING: { label: 'No prazo', icon: 'timer', css: 'running' },
  PAUSED: { label: 'Pausado', icon: 'pause_circle', css: 'paused' },
  MET: { label: 'Cumprido', icon: 'task_alt', css: 'met' },
  BREACHED: { label: 'Violado', icon: 'error', css: 'breached' },
  OVERDUE: { label: 'Atrasado', icon: 'error', css: 'breached' },
  AT_RISK: { label: 'Em risco', icon: 'warning', css: 'at-risk' }
};
const KIND: Record<string, string> = { FIRST_RESPONSE: 'primeira resposta', RESOLUTION: 'resolução' };

/** Situação do SLA do chamado (ADR-017): estado, próximos prazos e violações. Sem SLA, não mostra nada. */
@Component({
  selector: 'app-sla-badge',
  standalone: true,
  imports: [DatePipe, MatIconModule, MatTooltipModule],
  template: `
    @if (view(); as v) {
      <span class="sla" [class]="v.css" data-testid="sla-badge" [matTooltip]="v.tooltip">
        <mat-icon>{{ v.icon }}</mat-icon>
        @if (!compact()) { SLA: }{{ v.label }}
        @if (v.due) { · {{ v.dueLabel }} {{ v.due | date:'dd/MM HH:mm' }} }
      </span>
    }
  `,
  styles: [`
    .sla { display: inline-flex; align-items: center; gap: 4px; font-size: 13px; padding: 4px 10px; border-radius: 14px; }
    .sla mat-icon { font-size: 16px; width: 16px; height: 16px; }
    .running { background: #e0f2fe; color: #075985; }
    .paused { background: #f1f5f9; color: #475569; }
    .at-risk { background: #fef3c7; color: #92400e; }
    .met { background: #dcfce7; color: #166534; }
    .breached { background: #fee2e2; color: #991b1b; }
  `]
})
export class SlaBadgeComponent {
  sla = input<SlaInfo | null | undefined>(null);
  /** Lista de chamados: sem o prefixo "SLA:". */
  compact = input(false);

  view = computed(() => {
    const s = this.sla();
    if (!s || s.state === 'NOT_APPLICABLE') return null;
    const breaches = s.breaches ?? [];
    const late = breaches.length > 0 && s.state !== 'MET';
    let base = late && s.state !== 'BREACHED' ? STATE['BREACHED'] : STATE[s.state];
    if (!late && s.overdue) base = STATE['OVERDUE'];
    else if (!late && s.at_risk) base = STATE['AT_RISK'];
    const waitingFirst = !s.first_response_at && !!s.first_response_due_at;
    const due = s.state === 'RUNNING' ? (waitingFirst ? s.first_response_due_at : s.resolution_due_at) : null;
    const lines = [`Política: ${s.policy_name ?? '-'}`];
    if (s.first_response_due_at) lines.push(`Primeira resposta até ${this.fmt(s.first_response_due_at)}`);
    if (s.first_response_at) lines.push(`Respondido em ${this.fmt(s.first_response_at)}`);
    if (s.resolution_due_at) lines.push(`Resolução até ${this.fmt(s.resolution_due_at)}`);
    if (s.state === 'PAUSED') lines.push('Relógio parado enquanto o chamado está pausado');
    if (breaches.length) lines.push(`Prazo vencido: ${breaches.map((b) => KIND[b] ?? b).join(' e ')}`);
    return {
      ...base,
      due,
      dueLabel: waitingFirst ? 'responder até' : 'resolver até',
      tooltip: lines.join('\n')
    };
  });

  private fmt(iso: string): string {
    return new Date(iso).toLocaleString('pt-BR', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' });
  }
}
