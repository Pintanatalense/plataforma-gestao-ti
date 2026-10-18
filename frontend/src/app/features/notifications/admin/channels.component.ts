import { Component, DestroyRef, NgZone, OnInit, inject, signal } from '@angular/core';
import { CommonModule, DatePipe } from '@angular/common';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatSlideToggleModule } from '@angular/material/slide-toggle';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { HealthResponse, JobItem, NotificationsAdminService } from '../../../core/services/notifications-admin.service';

const REFRESH_MS = 15_000;

export const CHANNEL_NAMES: Record<string, string> = { in_app: 'Caixa de entrada', email: 'E-mail', telegram: 'Telegram', whatsapp: 'WhatsApp' };
export const WORKER_LABELS: Record<string, string> = {
  healthy: 'Funcionando',
  stale: 'Sem sinal (parado há mais de 1 min)',
  stopped: 'Nunca iniciou'
};

/** Estado de um canal para exibição: o pior sinal vence. */
export function channelState(c: { enabled: boolean; circuit_open: boolean; dead: number }): 'off' | 'degraded' | 'attention' | 'ok' {
  if (!c.enabled) return 'off';
  if (c.circuit_open) return 'degraded';
  if (c.dead > 0) return 'attention';
  return 'ok';
}

@Component({
  selector: 'app-channels',
  standalone: true,
  imports: [CommonModule, DatePipe, MatButtonModule, MatIconModule, MatSlideToggleModule, MatSnackBarModule],
  template: `
    @if (health(); as h) {
      <section class="worker" [class]="'w-' + h.worker.status" data-testid="worker-status">
        <mat-icon>{{ h.worker.status === 'healthy' ? 'check_circle' : 'error' }}</mat-icon>
        <div>
          <strong>Worker de notificações: {{ workerLabel(h.worker.status) }}</strong>
          @if (h.worker.beat_at) {
            <span>Último sinal: {{ h.worker.beat_at | date: 'dd/MM HH:mm:ss' }}</span>
          }
          @if (h.events_waiting.count > 0) {
            <span>{{ h.events_waiting.count }} evento(s) aguardando processamento desde {{ h.events_waiting.oldest_at | date: 'dd/MM HH:mm' }}</span>
          }
        </div>
      </section>

      <div class="cards">
        @for (c of h.channels; track c.channel) {
          <article class="card" [class]="'st-' + state(c)" data-testid="channel-card">
            <header>
              <h3>{{ name(c.channel) }}</h3>
              <span class="badge">{{ stateLabel(c) }}</span>
            </header>
            <dl>
              <dt>Pendentes</dt><dd>{{ c.pending }}</dd>
              <dt>Falhas definitivas</dt><dd>{{ c.dead }}</dd>
              <dt>Enviadas</dt><dd>{{ c.sent }}</dd>
              <dt>Falhas na última hora</dt><dd>{{ c.failures_last_hour }} de {{ c.attempts_last_hour }}</dd>
              <dt>Último envio</dt><dd>{{ c.last_sent_at ? (c.last_sent_at | date: 'dd/MM HH:mm') : '—' }}</dd>
              @if (c.oldest_pending_at) {
                <dt>Pendente mais antiga</dt><dd>{{ c.oldest_pending_at | date: 'dd/MM HH:mm' }}</dd>
              }
            </dl>
            @if (c.last_error) {
              <p class="error">Último erro ({{ c.last_error_at | date: 'dd/MM HH:mm' }}): {{ c.last_error }}</p>
            }
            <button mat-stroked-button (click)="test(c.channel)" [attr.data-testid]="'test-' + c.channel">Testar canal</button>
            @if (testResult()[c.channel]; as r) {
              <p [class.error]="!r.ok">{{ r.detail }}</p>
            }
          </article>
        }
      </div>
    } @else if (loadFailed()) {
      <p class="error" role="alert">Não foi possível carregar a saúde dos canais.</p>
    }

    <h3 class="jobs-title">Agenda do worker</h3>
    <div class="table-wrap">
      <table class="grid" data-testid="jobs-table">
        <thead><tr><th>Ativo</th><th>Tarefa</th><th>Agenda</th><th>Próxima</th><th>Última</th><th></th></tr></thead>
        <tbody>
          @for (j of jobs(); track j.name) {
            <tr data-testid="job-row">
              <td><mat-slide-toggle [checked]="j.enabled" (change)="setEnabled(j, $event.checked)" aria-label="Ativar tarefa" /></td>
              <td><code>{{ j.name }}</code></td>
              <td>{{ j.schedule }}</td>
              <td>{{ j.next_run_at | date: 'dd/MM HH:mm' }}</td>
              <td>
                @if (j.last_run_at) {
                  {{ j.last_run_at | date: 'dd/MM HH:mm' }} — <span [class.error]="j.last_status === 'error'">{{ j.last_status }}</span>
                  @if (j.last_error) { <div class="error small">{{ j.last_error }}</div> }
                } @else { — }
              </td>
              <td class="row-actions">
                <button mat-button (click)="run(j)" [disabled]="!j.enabled" data-testid="run-job">Executar agora</button>
              </td>
            </tr>
          }
        </tbody>
      </table>
    </div>
  `,
  styles: [`
    .worker { display: flex; gap: 12px; align-items: center; padding: 12px 16px; border-radius: 8px; margin-top: 16px; background: #dcfce7; }
    .worker div { display: flex; flex-direction: column; font-size: 13px; }
    .worker.w-stale, .worker.w-stopped { background: #fee2e2; }
    .cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 16px; margin-top: 16px; }
    .card { border: 1px solid #e2e8f0; border-radius: 8px; padding: 16px; background: #fff; display: flex; flex-direction: column; gap: 8px; }
    .card header { display: flex; justify-content: space-between; align-items: center; }
    .card h3 { margin: 0; }
    .badge { padding: 2px 10px; border-radius: 12px; font-size: 12px; background: #dcfce7; }
    .st-off .badge { background: #e2e8f0; } .st-degraded .badge { background: #fee2e2; } .st-attention .badge { background: #fef9c3; }
    dl { display: grid; grid-template-columns: 1fr auto; gap: 4px 12px; margin: 0; font-size: 13px; }
    dt { color: #64748b; } dd { margin: 0; text-align: right; }
    .jobs-title { margin: 24px 0 8px; }
    .table-wrap { overflow-x: auto; }
    .grid { width: 100%; border-collapse: collapse; font-size: 13px; }
    .grid th { text-align: left; padding: 8px; border-bottom: 2px solid #e2e8f0; color: #475569; }
    .grid td { padding: 8px; border-bottom: 1px solid #f1f5f9; }
    .row-actions { text-align: right; white-space: nowrap; }
    .error { color: #dc2626; } .small { font-size: 12px; }
  `]
})
export class ChannelsComponent implements OnInit {
  private api = inject(NotificationsAdminService);
  private snack = inject(MatSnackBar);
  private destroyRef = inject(DestroyRef);
  private zone = inject(NgZone);

  health = signal<HealthResponse | null>(null);
  jobs = signal<JobItem[]>([]);
  loadFailed = signal(false);
  testResult = signal<Record<string, { ok: boolean; detail: string }>>({});

  ngOnInit(): void {
    this.refresh();
    // Fora da zona: um timer recorrente dentro dela impede a aplicação de ficar "estável" (testes e SSR).
    const timer = this.zone.runOutsideAngular(() =>
      setInterval(() => this.zone.run(() => this.refresh()), REFRESH_MS)
    );
    this.destroyRef.onDestroy(() => clearInterval(timer));
  }

  refresh(): void {
    this.api.health().subscribe({
      next: (h) => {
        this.health.set(h);
        this.loadFailed.set(false);
      },
      error: () => this.loadFailed.set(true)
    });
    this.api.listJobs().subscribe({ next: (r) => this.jobs.set(r.items), error: () => {} });
  }

  name(channel: string): string {
    return CHANNEL_NAMES[channel] ?? channel;
  }

  workerLabel(status: string): string {
    return WORKER_LABELS[status] ?? status;
  }

  state(c: { enabled: boolean; circuit_open: boolean; dead: number }) {
    return channelState(c);
  }

  stateLabel(c: { enabled: boolean; circuit_open: boolean; dead: number }): string {
    return { off: 'Desativado', degraded: 'Degradado (pausado)', attention: 'Atenção', ok: 'Normal' }[channelState(c)];
  }

  test(channel: string): void {
    this.api.testChannel(channel).subscribe({
      next: (r) => this.testResult.update((m) => ({ ...m, [channel]: { ok: r.ok, detail: r.detail } })),
      error: () => this.testResult.update((m) => ({ ...m, [channel]: { ok: false, detail: 'Falha ao testar o canal.' } }))
    });
  }

  setEnabled(job: JobItem, enabled: boolean): void {
    this.api.setJobEnabled(job.name, enabled).subscribe({ next: () => this.refresh(), error: () => this.refresh() });
  }

  run(job: JobItem): void {
    this.api.runJob(job.name).subscribe({
      next: () => {
        this.snack.open('Execução solicitada; o worker inicia em alguns segundos.', 'OK', { duration: 4000 });
        this.refresh();
      },
      error: () => this.snack.open('Não foi possível solicitar a execução.', 'OK', { duration: 4000 })
    });
  }
}
