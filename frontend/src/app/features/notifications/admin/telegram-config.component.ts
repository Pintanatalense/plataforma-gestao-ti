import { Component, OnInit, inject, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatSlideToggleModule } from '@angular/material/slide-toggle';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { NotificationsAdminService, TelegramConfig } from '../../../core/services/notifications-admin.service';
import { apiErrorMessage } from './rules.component';

@Component({
  selector: 'app-telegram-config',
  standalone: true,
  imports: [
    CommonModule, FormsModule,
    MatButtonModule, MatFormFieldModule, MatInputModule, MatSlideToggleModule, MatSnackBarModule
  ],
  template: `
    <section class="card" data-testid="telegram-config">
      <h3>Telegram</h3>
      <p class="hint">
        Crie um bot com o @BotFather e cole o token. O sistema busca as mensagens por long polling:
        nenhuma porta ou domínio precisa ser exposto. O token fica cifrado e nunca é exibido de volta.
      </p>
      @if (config(); as c) {
        <mat-slide-toggle [(ngModel)]="c.enabled" name="enabled" data-testid="tg-enabled">Canal habilitado</mat-slide-toggle>
        <mat-form-field appearance="outline">
          <mat-label>Token do bot</mat-label>
          <input matInput type="password" autocomplete="off" [(ngModel)]="c.bot_token" name="token" data-testid="tg-token" />
          <mat-hint>{{ c.bot_username ? 'Bot atual: @' + c.bot_username : 'Nenhum bot configurado' }}</mat-hint>
        </mat-form-field>
        <mat-form-field appearance="outline">
          <mat-label>Endereço do sistema (para links nas mensagens)</mat-label>
          <input matInput [(ngModel)]="c.app_base_url" name="base" placeholder="https://ti.suaempresa.com.br" />
        </mat-form-field>
        @if (error()) {
          <p class="error" role="alert">{{ error() }}</p>
        }
        <div class="footer">
          <button mat-flat-button color="primary" (click)="save()" [disabled]="saving()" data-testid="tg-save">Salvar</button>
        </div>
      } @else if (loadFailed()) {
        <p class="error" role="alert">Não foi possível carregar a configuração.</p>
      }
    </section>
  `,
  styles: [`
    .card { display: flex; flex-direction: column; gap: 8px; border: 1px solid #e2e8f0; border-radius: 8px; padding: 16px; margin-top: 24px; background: #fff; }
    h3 { margin: 0; }
    .hint { color: #64748b; font-size: 13px; margin: 0; }
    .footer { display: flex; justify-content: flex-end; }
    .error { color: #dc2626; margin: 0; }
  `]
})
export class TelegramConfigComponent implements OnInit {
  private api = inject(NotificationsAdminService);
  private snack = inject(MatSnackBar);

  config = signal<TelegramConfig | null>(null);
  saving = signal(false);
  error = signal('');
  loadFailed = signal(false);

  ngOnInit(): void {
    this.api.getTelegramConfig().subscribe({
      next: (c) => this.config.set(c),
      error: () => this.loadFailed.set(true)
    });
  }

  save(): void {
    const c = this.config();
    if (!c) return;
    this.error.set('');
    this.saving.set(true);
    this.api.saveTelegramConfig({ enabled: c.enabled, bot_token: c.bot_token, app_base_url: c.app_base_url }).subscribe({
      next: (saved) => {
        this.config.set(saved);
        this.saving.set(false);
        this.snack.open('Telegram salvo.', 'OK', { duration: 3000 });
      },
      error: (err) => {
        this.saving.set(false);
        this.error.set(apiErrorMessage(err, 'Não foi possível salvar o Telegram.'));
      }
    });
  }
}
