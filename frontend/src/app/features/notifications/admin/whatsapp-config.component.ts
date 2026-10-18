import { Component, OnInit, inject, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatSlideToggleModule } from '@angular/material/slide-toggle';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { NotificationsAdminService, WhatsAppConfig } from '../../../core/services/notifications-admin.service';
import { apiErrorMessage } from './rules.component';

/** URL completa do webhook a cadastrar na Meta (exige HTTPS público). */
export function webhookUrl(path: string, origin: string): string {
  return `${origin.replace(/\/$/, '')}${path}`;
}

@Component({
  selector: 'app-whatsapp-config',
  standalone: true,
  imports: [
    CommonModule, FormsModule,
    MatButtonModule, MatFormFieldModule, MatInputModule, MatSlideToggleModule, MatSnackBarModule
  ],
  template: `
    <section class="card" data-testid="whatsapp-config">
      <h3>WhatsApp (Meta Cloud API)</h3>
      <p class="hint">
        Use um app WhatsApp da Meta. Tokens ficam cifrados e não são exibidos de volta. Fora da janela de 24 h
        da conversa só vai mensagem de template aprovado, então cadastre abaixo o nome do seu template (uma variável).
      </p>
      @if (config(); as c) {
        <mat-slide-toggle [(ngModel)]="c.enabled" name="wa_enabled" data-testid="wa-enabled">Canal habilitado</mat-slide-toggle>
        <mat-form-field appearance="outline">
          <mat-label>Token de acesso (permanente)</mat-label>
          <input matInput type="password" autocomplete="off" [(ngModel)]="c.access_token" name="wa_token" data-testid="wa-token" />
        </mat-form-field>
        <mat-form-field appearance="outline">
          <mat-label>App Secret</mat-label>
          <input matInput type="password" autocomplete="off" [(ngModel)]="c.app_secret" name="wa_secret" data-testid="wa-secret" />
          <mat-hint>Valida a assinatura dos webhooks</mat-hint>
        </mat-form-field>
        <mat-form-field appearance="outline">
          <mat-label>Phone Number ID</mat-label>
          <input matInput [(ngModel)]="c.phone_number_id" name="wa_phone" />
          <mat-hint>{{ c.display_phone ? 'Número: ' + c.display_phone + (c.verified_name ? ' — ' + c.verified_name : '') : 'Ainda não validado' }}</mat-hint>
        </mat-form-field>
        <div class="row">
          <mat-form-field appearance="outline">
            <mat-label>Template aprovado</mat-label>
            <input matInput [(ngModel)]="c.template_name" name="wa_template" placeholder="aviso_ti" />
          </mat-form-field>
          <mat-form-field appearance="outline">
            <mat-label>Idioma</mat-label>
            <input matInput [(ngModel)]="c.template_language" name="wa_lang" />
          </mat-form-field>
          <mat-form-field appearance="outline">
            <mat-label>Versão da Graph API</mat-label>
            <input matInput [(ngModel)]="c.graph_version" name="wa_version" />
          </mat-form-field>
        </div>
        <mat-form-field appearance="outline">
          <mat-label>Endereço do sistema (links nas mensagens)</mat-label>
          <input matInput [(ngModel)]="c.app_base_url" name="wa_base" placeholder="https://ti.suaempresa.com.br" />
        </mat-form-field>

        <div class="webhook" data-testid="wa-webhook">
          <strong>Webhook na Meta</strong>
          <span>URL de callback: <code>{{ webhook() }}</code></span>
          <span>Token de verificação: <code>{{ c.verify_token || 'gerado ao salvar' }}</code></span>
          <span>Campo assinado: <code>messages</code></span>
        </div>

        @if (error()) {
          <p class="error" role="alert">{{ error() }}</p>
        }
        <div class="footer">
          <button mat-flat-button color="primary" (click)="save()" [disabled]="saving()" data-testid="wa-save">Salvar</button>
        </div>
      } @else if (loadFailed()) {
        <p class="error" role="alert">Não foi possível carregar a configuração.</p>
      }
    </section>
  `,
  styles: [`
    .card { display: flex; flex-direction: column; gap: 8px; border: 1px solid #e2e8f0; border-radius: 8px; padding: 16px; margin-top: 24px; background: #fff; }
    h3 { margin: 0; }
    .row { display: flex; flex-wrap: wrap; gap: 12px; }
    .row mat-form-field { flex: 1 1 160px; }
    .webhook { display: flex; flex-direction: column; gap: 2px; background: #f8fafc; border: 1px dashed #94a3b8; border-radius: 8px; padding: 12px; font-size: 13px; overflow-wrap: anywhere; }
    .hint { color: #64748b; font-size: 13px; margin: 0; }
    .footer { display: flex; justify-content: flex-end; }
    .error { color: #dc2626; margin: 0; }
  `]
})
export class WhatsAppConfigComponent implements OnInit {
  private api = inject(NotificationsAdminService);
  private snack = inject(MatSnackBar);

  config = signal<WhatsAppConfig | null>(null);
  saving = signal(false);
  error = signal('');
  loadFailed = signal(false);

  ngOnInit(): void {
    this.api.getWhatsAppConfig().subscribe({
      next: (c) => this.config.set(c),
      error: () => this.loadFailed.set(true)
    });
  }

  webhook(): string {
    return webhookUrl(this.config()?.webhook_path ?? '', window.location.origin);
  }

  save(): void {
    const c = this.config();
    if (!c) return;
    this.error.set('');
    this.saving.set(true);
    this.api
      .saveWhatsAppConfig({
        enabled: c.enabled, access_token: c.access_token, app_secret: c.app_secret, phone_number_id: c.phone_number_id.trim(),
        graph_version: c.graph_version.trim(), template_name: c.template_name.trim(),
        template_language: c.template_language.trim(), app_base_url: c.app_base_url.trim()
      })
      .subscribe({
        next: (saved) => {
          this.config.set(saved);
          this.saving.set(false);
          this.snack.open('WhatsApp salvo.', 'OK', { duration: 3000 });
        },
        error: (err) => {
          this.saving.set(false);
          this.error.set(apiErrorMessage(err, 'Não foi possível salvar o WhatsApp.'));
        }
      });
  }
}
