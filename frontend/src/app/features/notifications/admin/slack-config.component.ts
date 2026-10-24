import { Component, OnInit, inject, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatSlideToggleModule } from '@angular/material/slide-toggle';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { NotificationsAdminService, SlackConfig } from '../../../core/services/notifications-admin.service';
import { apiErrorMessage } from './rules.component';
import { webhookUrl } from './whatsapp-config.component';
import { ChannelSelfTestComponent } from './channel-self-test.component';

@Component({
  selector: 'app-slack-config',
  standalone: true,
  imports: [
    CommonModule, FormsModule,
    MatButtonModule, MatFormFieldModule, MatInputModule, MatSlideToggleModule, MatSnackBarModule, ChannelSelfTestComponent
  ],
  template: `
    <section class="card" data-testid="slack-config">
      <h3>Slack</h3>
      <p class="hint">
        Crie um app no Slack com os escopos <code>chat:write</code>, <code>im:history</code> e <code>users:read</code>, ative
        "Event Subscriptions" (evento <code>message.im</code>) e a aba "Messages" do App Home. Tokens ficam cifrados e
        não são exibidos de volta. Exige uma URL HTTPS pública para receber as mensagens.
      </p>
      @if (config(); as c) {
        <mat-slide-toggle [(ngModel)]="c.enabled" name="sl_enabled" data-testid="sl-enabled">Canal habilitado</mat-slide-toggle>
        <mat-form-field appearance="outline">
          <mat-label>Bot User OAuth Token (xoxb-…)</mat-label>
          <input matInput type="password" autocomplete="off" [(ngModel)]="c.bot_token" name="sl_token" data-testid="sl-token" />
          <mat-hint>{{ c.bot_name ? 'App atual: ' + c.bot_name + (c.team_name ? ' em ' + c.team_name : '') : 'Nenhum app configurado' }}</mat-hint>
        </mat-form-field>
        <mat-form-field appearance="outline">
          <mat-label>Signing Secret</mat-label>
          <input matInput type="password" autocomplete="off" [(ngModel)]="c.signing_secret" name="sl_secret" data-testid="sl-secret" />
          <mat-hint>Valida a assinatura dos eventos</mat-hint>
        </mat-form-field>
        <mat-form-field appearance="outline">
          <mat-label>Endereço do sistema (links nas mensagens)</mat-label>
          <input matInput [(ngModel)]="c.app_base_url" name="sl_base" placeholder="https://ti.suaempresa.com.br" />
        </mat-form-field>

        <div class="webhook" data-testid="sl-webhook">
          <strong>Request URL no Slack (Event Subscriptions)</strong>
          <code>{{ eventsUrl() }}</code>
        </div>

        @if (error()) {
          <p class="error" role="alert">{{ error() }}</p>
        }
        <div class="footer">
          <button mat-flat-button color="primary" (click)="save()" [disabled]="saving()" data-testid="sl-save">Salvar</button>
        </div>
        @if (c.enabled && c.bot_name) {
          <app-channel-self-test channel="slack" />
        }
      } @else if (loadFailed()) {
        <p class="error" role="alert">Não foi possível carregar a configuração.</p>
      }
    </section>
  `,
  styles: [`
    .card { display: flex; flex-direction: column; gap: 8px; border: 1px solid #e2e8f0; border-radius: 8px; padding: 16px; margin-top: 24px; background: #fff; }
    h3 { margin: 0; }
    .webhook { display: flex; flex-direction: column; gap: 2px; background: #f8fafc; border: 1px dashed #94a3b8; border-radius: 8px; padding: 12px; font-size: 13px; overflow-wrap: anywhere; }
    .hint { color: #64748b; font-size: 13px; margin: 0; }
    .footer { display: flex; justify-content: flex-end; }
    .error { color: #dc2626; margin: 0; }
  `]
})
export class SlackConfigComponent implements OnInit {
  private api = inject(NotificationsAdminService);
  private snack = inject(MatSnackBar);

  config = signal<SlackConfig | null>(null);
  saving = signal(false);
  error = signal('');
  loadFailed = signal(false);

  ngOnInit(): void {
    this.api.getSlackConfig().subscribe({
      next: (c) => this.config.set(c),
      error: () => this.loadFailed.set(true)
    });
  }

  eventsUrl(): string {
    return webhookUrl(this.config()?.events_path ?? '', window.location.origin);
  }

  save(): void {
    const c = this.config();
    if (!c) return;
    this.error.set('');
    this.saving.set(true);
    this.api
      .saveSlackConfig({
        enabled: c.enabled, bot_token: c.bot_token, signing_secret: c.signing_secret, app_base_url: c.app_base_url.trim()
      })
      .subscribe({
        next: (saved) => {
          this.config.set(saved);
          this.saving.set(false);
          this.snack.open('Slack salvo.', 'OK', { duration: 3000 });
        },
        error: (err) => {
          this.saving.set(false);
          this.error.set(apiErrorMessage(err, 'Não foi possível salvar o Slack.'));
        }
      });
  }
}
