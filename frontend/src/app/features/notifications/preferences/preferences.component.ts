import { Component, OnInit, inject, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatSlideToggleModule } from '@angular/material/slide-toggle';
import { MatCheckboxModule } from '@angular/material/checkbox';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { NotificationPrefs, NotificationsService } from '../../../core/services/notifications.service';
import { MyChannelsComponent } from './my-channels.component';
import { PushSettingsComponent } from './push-settings.component';

export const CHANNEL_LABELS: Record<string, string> = { email: 'E-mail', telegram: 'Telegram', whatsapp: 'WhatsApp', slack: 'Slack', webpush: 'Pop-up no navegador' };
export const CATEGORY_LABELS: Record<string, string> = {
  ticket: 'Chamados',
  asset: 'Ativos',
  stock: 'Estoque e inventário',
  system: 'Sistema (backups, canais)'
};

const HHMM = /^([01]\d|2[0-3]):[0-5]\d$/;

/** Marca/desmarca um item numa lista de itens desligados (lista = o que está DESLIGADO). */
export function toggleDisabled(list: string[], item: string, enabled: boolean): string[] {
  const without = list.filter((x) => x !== item);
  return enabled ? without : [...without, item].sort();
}

@Component({
  selector: 'app-notification-preferences',
  standalone: true,
  imports: [
    CommonModule, FormsModule, RouterLink,
    MatButtonModule, MatIconModule, MatSlideToggleModule, MatCheckboxModule,
    MatFormFieldModule, MatInputModule, MatSnackBarModule, MyChannelsComponent, PushSettingsComponent
  ],
  template: `
    <div class="page">
      <header class="page-header">
        <div>
          <h1>Preferências de notificação</h1>
          <p class="subtitle">A caixa de entrada do sistema está sempre ativa. Aqui você ajusta o que chega por fora (e-mail).</p>
        </div>
        <a mat-stroked-button routerLink="/notifications"><mat-icon>arrow_back</mat-icon> Caixa de entrada</a>
      </header>

      <app-push-settings />
      <app-my-channels />

      @if (prefs(); as p) {
        <section class="card">
          <h2>Quais canais usar</h2>
          @for (channel of p.available_channels ?? []; track channel) {
            <mat-slide-toggle
              [checked]="!p.channels_disabled.includes(channel)"
              (change)="setChannel(channel, $event.checked)"
              [attr.data-testid]="'channel-' + channel">
              {{ channelLabel(channel) }}
            </mat-slide-toggle>
          }
        </section>

        <section class="card">
          <h2>O que receber por fora</h2>
          @for (category of p.available_categories ?? []; track category) {
            <mat-checkbox
              [checked]="!p.categories_disabled.includes(category)"
              (change)="setCategory(category, $event.checked)"
              [attr.data-testid]="'category-' + category">
              {{ categoryLabel(category) }}
            </mat-checkbox>
          }
          <p class="hint">Desmarcar uma categoria silencia só os canais externos; os avisos continuam na caixa de entrada.</p>
        </section>

        <section class="card">
          <h2>Horário de silêncio</h2>
          <mat-slide-toggle [(ngModel)]="p.quiet_enabled" data-testid="quiet-enabled">Adiar e-mails fora do horário</mat-slide-toggle>
          <div class="times">
            <mat-form-field appearance="outline">
              <mat-label>Início</mat-label>
              <input matInput type="time" [(ngModel)]="p.quiet_start" [disabled]="!p.quiet_enabled" data-testid="quiet-start" />
            </mat-form-field>
            <mat-form-field appearance="outline">
              <mat-label>Fim</mat-label>
              <input matInput type="time" [(ngModel)]="p.quiet_end" [disabled]="!p.quiet_enabled" data-testid="quiet-end" />
            </mat-form-field>
          </div>
          <mat-checkbox [(ngModel)]="p.critical_bypass" [disabled]="!p.quiet_enabled">
            Avisos críticos (ex.: falha de backup) ignoram o silêncio
          </mat-checkbox>
          <p class="hint">Fuso: {{ p.timezone }}. Mensagens adiadas saem quando a janela termina.</p>
        </section>

        @if (error()) {
          <p class="error" role="alert">{{ error() }}</p>
        }
        <div class="footer">
          <button mat-flat-button color="primary" (click)="save()" [disabled]="saving()" data-testid="save">
            <mat-icon>save</mat-icon> Salvar
          </button>
        </div>
      } @else if (loadFailed()) {
        <p class="error" role="alert">Não foi possível carregar as preferências.</p>
      }
    </div>
  `,
  styles: [`
    .page { max-width: 720px; margin: 0 auto; padding: 24px 16px; }
    .page-header { display: flex; flex-wrap: wrap; gap: 12px; justify-content: space-between; align-items: flex-start; }
    h1 { margin: 0; font-size: 24px; }
    h2 { font-size: 16px; margin: 0 0 8px; }
    .subtitle, .hint { color: #64748b; margin: 4px 0 0; font-size: 13px; }
    .card { display: flex; flex-direction: column; gap: 8px; border: 1px solid #e2e8f0; border-radius: 8px; padding: 16px; margin-top: 16px; background: #fff; }
    .times { display: flex; gap: 12px; flex-wrap: wrap; }
    .times mat-form-field { flex: 1 1 140px; }
    .footer { margin-top: 16px; display: flex; justify-content: flex-end; }
    .error { color: #dc2626; }
  `]
})
export class PreferencesComponent implements OnInit {
  private service = inject(NotificationsService);
  private snack = inject(MatSnackBar);

  prefs = signal<NotificationPrefs | null>(null);
  saving = signal(false);
  error = signal('');
  loadFailed = signal(false);

  ngOnInit(): void {
    this.service.getPrefs().subscribe({
      next: (p) => this.prefs.set(p),
      error: () => this.loadFailed.set(true)
    });
  }

  channelLabel(channel: string): string {
    return CHANNEL_LABELS[channel] ?? channel;
  }

  categoryLabel(category: string): string {
    return CATEGORY_LABELS[category] ?? category;
  }

  setChannel(channel: string, enabled: boolean): void {
    const p = this.prefs();
    if (p) p.channels_disabled = toggleDisabled(p.channels_disabled, channel, enabled);
  }

  setCategory(category: string, enabled: boolean): void {
    const p = this.prefs();
    if (p) p.categories_disabled = toggleDisabled(p.categories_disabled, category, enabled);
  }

  save(): void {
    const p = this.prefs();
    if (!p) return;
    if (p.quiet_enabled && (!HHMM.test(p.quiet_start) || !HHMM.test(p.quiet_end))) {
      this.error.set('Informe início e fim no formato HH:MM.');
      return;
    }
    this.error.set('');
    this.saving.set(true);
    this.service.savePrefs(p).subscribe({
      next: (saved) => {
        this.prefs.set(saved);
        this.saving.set(false);
        this.snack.open('Preferências salvas.', 'OK', { duration: 3000 });
      },
      error: () => {
        this.saving.set(false);
        this.error.set('Não foi possível salvar. Verifique os valores e tente novamente.');
      }
    });
  }
}
