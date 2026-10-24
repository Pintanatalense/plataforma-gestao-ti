import { Component, DestroyRef, NgZone, OnInit, inject, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatButtonToggleModule } from '@angular/material/button-toggle';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatSlideToggleModule } from '@angular/material/slide-toggle';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { NotificationsAdminService, WhatsAppConfig, WhatsAppConnect, WhatsAppProvider, WhatsAppStatus } from '../../../core/services/notifications-admin.service';
import { apiErrorMessage } from './rules.component';

/** URL completa do webhook a cadastrar na Meta (exige HTTPS público). */
export function webhookUrl(path: string, origin: string): string {
  return `${origin.replace(/\/$/, '')}${path}`;
}

/** Atualização do QR code enquanto o número não é pareado (o código gira a cada poucos segundos). */
const QR_REFRESH_MS = 5_000;

export const STATE_LABELS: Record<string, string> = {
  open: 'Conectado',
  connecting: 'Aguardando leitura do QR code',
  close: 'Desconectado',
  unconfigured: 'Servidor sem a chave da Evolution',
  error: 'Erro ao consultar a Evolution'
};

/** Só imagens embutidas: o QR vem do servidor, mas o `src` nunca deve aceitar outra coisa. */
export function safeQr(value: string | null | undefined): string | null {
  return value && /^data:image\/(png|jpeg);base64,[A-Za-z0-9+/=]+$/.test(value) ? value : null;
}

@Component({
  selector: 'app-whatsapp-config',
  standalone: true,
  imports: [
    CommonModule, FormsModule,
    MatButtonModule, MatButtonToggleModule, MatFormFieldModule, MatInputModule, MatSlideToggleModule, MatSnackBarModule
  ],
  template: `
    <section class="card" data-testid="whatsapp-config">
      <h3>WhatsApp</h3>
      @if (config(); as c) {
        <mat-button-toggle-group [ngModel]="c.provider" (ngModelChange)="setProvider($event)" name="wa_provider" aria-label="Provedor do WhatsApp" data-testid="wa-provider">
          <mat-button-toggle value="evolution">Evolution API (sem custo)</mat-button-toggle>
          <mat-button-toggle value="meta">Meta Cloud API (oficial)</mat-button-toggle>
        </mat-button-toggle-group>

        @if (c.provider === 'evolution') {
          <p class="hint" data-testid="wa-evolution-hint">
            Sem custo por mensagem, mas <strong>não é oficial</strong>: use um chip dedicado (nunca o WhatsApp pessoal de alguém),
            porque o WhatsApp pode desconectar a sessão ou banir o número. Só recebe quem vinculou o próprio número, e o e-mail
            continua nos alertas como rede de segurança.
          </p>
          @if (!c.evolution_ready) {
            <p class="error" role="alert" data-testid="wa-not-ready">
              Este servidor ainda não tem a Evolution: defina <code>EVOLUTION_API_KEY</code> no <code>.env</code> e suba o serviço com
              <code>docker compose --profile whatsapp up -d</code>.
            </p>
          }
        } @else {
          <p class="hint">
            Use um app WhatsApp da Meta. Tokens ficam cifrados e não são exibidos de volta. Fora da janela de 24 h
            da conversa só vai mensagem de template aprovado, então cadastre abaixo o nome do seu template (uma variável).
          </p>
        }

        <mat-slide-toggle [(ngModel)]="c.enabled" name="wa_enabled" data-testid="wa-enabled">Canal habilitado</mat-slide-toggle>

        @if (c.provider === 'evolution') {
          <mat-form-field appearance="outline">
            <mat-label>Nome da instância</mat-label>
            <input matInput [(ngModel)]="c.instance_name" name="wa_instance" data-testid="wa-instance" />
            <mat-hint>Letras, números, hífen e sublinhado</mat-hint>
          </mat-form-field>
        } @else {
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
        }

        <mat-form-field appearance="outline">
          <mat-label>Endereço do sistema (links nas mensagens)</mat-label>
          <input matInput [(ngModel)]="c.app_base_url" name="wa_base" placeholder="https://ti.suaempresa.com.br" />
        </mat-form-field>

        @if (c.provider === 'meta') {
          <div class="webhook" data-testid="wa-webhook">
            <strong>Webhook na Meta</strong>
            <span>URL de callback: <code>{{ webhook() }}</code></span>
            <span>Token de verificação: <code>{{ c.verify_token || 'gerado ao salvar' }}</code></span>
            <span>Campo assinado: <code>messages</code></span>
          </div>
        }

        @if (error()) {
          <p class="error" role="alert">{{ error() }}</p>
        }
        <div class="footer">
          <button mat-flat-button color="primary" (click)="save()" [disabled]="saving()" data-testid="wa-save">Salvar</button>
        </div>

        @if (c.provider === 'evolution') {
          <div class="connection" data-testid="wa-connection">
            <strong>Conexão do número</strong>
            @if (status(); as s) {
              <span data-testid="wa-state" [class.ok]="s.state === 'open'">
                {{ stateLabel(s.state) }}@if (s.display_phone) { — {{ s.display_phone }} }
              </span>
              @if (s.detail) { <span class="error">{{ s.detail }}</span> }
            } @else if (statusFailed()) {
              <span class="error" role="alert">Não foi possível consultar o estado da conexão.</span>
            }
            @if (qr(); as image) {
              <img [src]="image" alt="QR code para parear o WhatsApp" width="240" height="240" data-testid="wa-qr" />
              <span class="hint">No celular do chip dedicado: WhatsApp → Aparelhos conectados → Conectar um aparelho. O código troca sozinho.</span>
            }
            <div class="footer">
              <button mat-stroked-button (click)="connect()" [disabled]="connecting()" data-testid="wa-connect">
                {{ qr() ? 'Atualizar QR code' : 'Conectar número' }}
              </button>
              <button mat-button (click)="disconnect()" [disabled]="connecting() || status()?.state !== 'open'" data-testid="wa-disconnect">Desconectar</button>
            </div>
            <span class="hint">Salve o provedor antes de conectar.</span>
          </div>
        }
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
    .webhook, .connection { display: flex; flex-direction: column; gap: 4px; background: #f8fafc; border: 1px dashed #94a3b8; border-radius: 8px; padding: 12px; font-size: 13px; overflow-wrap: anywhere; }
    .connection img { align-self: center; background: #fff; padding: 8px; border: 1px solid #e2e8f0; }
    .connection .footer { justify-content: flex-start; gap: 8px; }
    .ok { color: #166534; font-weight: 500; }
    .hint { color: #64748b; font-size: 13px; margin: 0; }
    .footer { display: flex; justify-content: flex-end; }
    .error { color: #dc2626; margin: 0; }
  `]
})
export class WhatsAppConfigComponent implements OnInit {
  private api = inject(NotificationsAdminService);
  private snack = inject(MatSnackBar);
  private zone = inject(NgZone);
  private destroyRef = inject(DestroyRef);

  config = signal<WhatsAppConfig | null>(null);
  saving = signal(false);
  error = signal('');
  loadFailed = signal(false);

  status = signal<WhatsAppStatus | null>(null);
  statusFailed = signal(false);
  qr = signal<string | null>(null);
  connecting = signal(false);
  private timer: ReturnType<typeof setInterval> | null = null;

  ngOnInit(): void {
    this.destroyRef.onDestroy(() => this.stopRefresh());
    this.api.getWhatsAppConfig().subscribe({
      next: (c) => {
        this.config.set({ ...c, provider: c.provider ?? 'meta', instance_name: c.instance_name ?? 'gestao-ti' });
        if (this.config()!.provider === 'evolution') this.loadStatus();
      },
      error: () => this.loadFailed.set(true)
    });
  }

  webhook(): string {
    return webhookUrl(this.config()?.webhook_path ?? '', window.location.origin);
  }

  stateLabel(state: string): string {
    return STATE_LABELS[state] ?? state;
  }

  setProvider(provider: WhatsAppProvider): void {
    this.config.update((c) => (c ? { ...c, provider } : c));
    this.stopRefresh();
    this.qr.set(null);
  }

  private loadStatus(): void {
    this.api.whatsAppStatus().subscribe({
      next: (s) => {
        this.status.set(s);
        this.statusFailed.set(false);
      },
      error: () => this.statusFailed.set(true)
    });
  }

  connect(): void {
    this.connecting.set(true);
    this.api.whatsAppConnect().subscribe({
      next: (r) => {
        this.connecting.set(false);
        this.applyConnect(r);
      },
      error: (err) => {
        this.connecting.set(false);
        this.stopRefresh();
        this.snack.open(apiErrorMessage(err, 'Não foi possível iniciar a conexão.'), 'Fechar', { duration: 6000 });
      }
    });
  }

  private applyConnect(r: WhatsAppConnect): void {
    this.status.set(r);
    this.qr.set(r.state === 'connecting' ? safeQr(r.qr_base64) : null);
    if (r.state === 'connecting') {
      this.startRefresh();
    } else {
      this.stopRefresh();
      if (r.state === 'open') this.snack.open('WhatsApp conectado.', 'OK', { duration: 3000 });
    }
  }

  private startRefresh(): void {
    if (this.timer) return;
    // Fora da zona: um timer recorrente dentro dela impede a aplicação de ficar "estável" (testes e SSR).
    this.timer = this.zone.runOutsideAngular(() =>
      setInterval(() => this.zone.run(() => this.refreshQr()), QR_REFRESH_MS)
    );
  }

  private stopRefresh(): void {
    if (this.timer) clearInterval(this.timer);
    this.timer = null;
  }

  private refreshQr(): void {
    this.api.whatsAppConnect().subscribe({
      next: (r) => this.applyConnect(r),
      error: () => this.stopRefresh()
    });
  }

  disconnect(): void {
    this.connecting.set(true);
    this.api.whatsAppDisconnect().subscribe({
      next: (s) => {
        this.connecting.set(false);
        this.stopRefresh();
        this.qr.set(null);
        this.status.set({ ...s, detail: '', display_phone: null });
        this.snack.open('WhatsApp desconectado.', 'OK', { duration: 3000 });
      },
      error: (err) => {
        this.connecting.set(false);
        this.snack.open(apiErrorMessage(err, 'Não foi possível desconectar.'), 'Fechar', { duration: 6000 });
      }
    });
  }

  save(): void {
    const c = this.config();
    if (!c) return;
    this.error.set('');
    this.saving.set(true);
    this.api
      .saveWhatsAppConfig({
        enabled: c.enabled, provider: c.provider, instance_name: c.instance_name.trim(),
        access_token: c.access_token, app_secret: c.app_secret, phone_number_id: c.phone_number_id.trim(),
        graph_version: c.graph_version.trim(), template_name: c.template_name.trim(),
        template_language: c.template_language.trim(), app_base_url: c.app_base_url.trim()
      })
      .subscribe({
        next: (saved) => {
          this.config.set(saved);
          this.saving.set(false);
          this.snack.open('WhatsApp salvo.', 'OK', { duration: 3000 });
          if (saved.provider === 'evolution') this.loadStatus();
        },
        error: (err) => {
          this.saving.set(false);
          this.error.set(apiErrorMessage(err, 'Não foi possível salvar o WhatsApp.'));
        }
      });
  }
}
