import { ChangeDetectorRef, Component, OnInit, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { MatCardModule } from '@angular/material/card';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';
import { MatSlideToggleModule } from '@angular/material/slide-toggle';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { apiErrorMessage } from '../../core/http/api-error';
import { AdminService, PasswordResetConfig, SmtpConfig } from '../../core/services/admin.service';
import { LoadStateComponent } from '../../shared/components/load-state/load-state.component';

/** Aba E-mail: servidor SMTP, envio de teste e recuperação de senha (que depende do SMTP homologado). */
@Component({
  selector: 'app-email-config',
  standalone: true,
  imports: [
    CommonModule, FormsModule,
    MatCardModule, MatButtonModule, MatIconModule, MatFormFieldModule, MatInputModule, MatSelectModule,
    MatSlideToggleModule, MatSnackBarModule, LoadStateComponent
  ],
  template: `
    <div class="two-column-grid">
      <mat-card class="admin-card">
        <mat-card-header>
          <mat-icon mat-card-avatar color="primary">mail_lock</mat-icon>
          <mat-card-title>Parâmetros do Servidor SMTP</mat-card-title>
          <mat-card-subtitle>Envio de notificações de chamados e alertas transacionais</mat-card-subtitle>
        </mat-card-header>
        <mat-card-content>
          <app-load-state [error]="smtpLoadError" (retry)="loadSmtpConfig()"></app-load-state>
          <div class="status-toggle-box" [class.active]="smtpConfig.is_enabled">
            <div class="toggle-info">
              <strong>Notificações por E-mail</strong>
              <span>{{ smtpConfig.is_enabled ? 'Disparos automáticos ativados' : 'Disparos automáticos desativados' }}</span>
            </div>
            <mat-slide-toggle [(ngModel)]="smtpConfig.is_enabled" color="primary"></mat-slide-toggle>
          </div>

          <div class="form-grid">
            <mat-form-field appearance="outline" class="full-width">
              <mat-label>Servidor SMTP (Host)</mat-label>
              <input matInput [(ngModel)]="smtpConfig.host" placeholder="Ex: smtp.gmail.com ou smtp.office365.com">
            </mat-form-field>

            <div class="pair">
              <mat-form-field appearance="outline">
                <mat-label>Porta</mat-label>
                <input matInput type="number" [(ngModel)]="smtpConfig.port" placeholder="587">
              </mat-form-field>

              <mat-form-field appearance="outline">
                <mat-label>Segurança da Conexão</mat-label>
                <mat-select [(ngModel)]="smtpConfig.security">
                  <mat-option value="STARTTLS">STARTTLS (Porta 587 comum)</mat-option>
                  <mat-option value="SSL_TLS">SSL / TLS (Porta 465)</mat-option>
                  <mat-option value="NONE">Sem Criptografia (Porta 25)</mat-option>
                </mat-select>
              </mat-form-field>
            </div>

            <div class="pair">
              <mat-form-field appearance="outline">
                <mat-label>Usuário / E-mail de Autenticação</mat-label>
                <input matInput [(ngModel)]="smtpConfig.username" placeholder="usuario@empresa.com.br">
              </mat-form-field>

              <mat-form-field appearance="outline">
                <mat-label>Senha / App Password</mat-label>
                <input matInput type="password" [(ngModel)]="smtpPasswordInput" placeholder="Digite para alterar a senha">
              </mat-form-field>
            </div>

            <div class="pair">
              <mat-form-field appearance="outline">
                <mat-label>E-mail do Remetente (From)</mat-label>
                <input matInput [(ngModel)]="smtpConfig.from_email" placeholder="suporte@empresa.com.br">
              </mat-form-field>

              <mat-form-field appearance="outline">
                <mat-label>Nome de Exibição do Remetente</mat-label>
                <input matInput [(ngModel)]="smtpConfig.from_name" placeholder="Service Desk - Gestão de TI">
              </mat-form-field>
            </div>

            <mat-form-field appearance="outline" class="full-width">
              <mat-label>URL Base da Plataforma (para links nos e-mails)</mat-label>
              <input matInput [(ngModel)]="smtpConfig.app_base_url" placeholder="http://localhost ou https://chamados.empresa.com.br">
            </mat-form-field>
          </div>

          <div class="action-row">
            <button mat-flat-button color="primary" [disabled]="savingSmtpConfig || loadingSmtpConfig || !!smtpLoadError" (click)="saveSmtpConfig()">
              <mat-icon>save</mat-icon> Salvar Parâmetros SMTP
            </button>
          </div>
        </mat-card-content>
      </mat-card>

      <mat-card class="admin-card">
        <mat-card-header>
          <mat-icon mat-card-avatar color="accent">send_and_archive</mat-icon>
          <mat-card-title>Validação de Conectividade</mat-card-title>
          <mat-card-subtitle>Teste a entrega e autenticação antes de ativar em produção</mat-card-subtitle>
        </mat-card-header>
        <mat-card-content>
          <p class="note">Envie um e-mail de teste para verificar se o host, a porta, o certificado TLS e as credenciais estão aceitando conexões:</p>

          <mat-form-field appearance="outline" class="full-width">
            <mat-label>E-mail de Destino para Teste</mat-label>
            <input matInput [(ngModel)]="testSmtpEmail" placeholder="seu.email@empresa.com.br">
          </mat-form-field>

          <button mat-flat-button color="accent" [disabled]="testingSmtp || !testSmtpEmail" (click)="runSmtpTest()">
            <mat-icon>send</mat-icon> {{ testingSmtp ? 'Enviando teste...' : 'Enviar E-mail de Teste' }}
          </button>

          @if (smtpTestFeedback; as fb) {
            <div class="feedback" [class.ok]="fb.success" [class.bad]="!fb.success">
              <mat-icon>{{ fb.success ? 'check_circle' : 'error' }}</mat-icon>
              <span>{{ fb.message }}</span>
            </div>
          }

          <div class="privacy">
            <mat-icon>policy</mat-icon>
            <div>
              <strong>Garantia de Privacidade DEC-012:</strong>
              <span>O sistema assegura que notas e comentários marcados como <em>"Internos"</em> JAMAIS são enviados ao solicitante por e-mail. Apenas respostas públicas notificam clientes finais.</span>
            </div>
          </div>
        </mat-card-content>
      </mat-card>

      <mat-card class="admin-card" data-testid="password-reset-card">
        <mat-card-header>
          <mat-icon mat-card-avatar color="primary">lock_reset</mat-icon>
          <mat-card-title>Recuperação de senha por e-mail</mat-card-title>
          <mat-card-subtitle>"Esqueci minha senha" na tela de login (desativada por padrão)</mat-card-subtitle>
        </mat-card-header>
        <mat-card-content>
          <app-load-state [error]="passwordResetError" (retry)="loadPasswordReset()"></app-load-state>
          @if (passwordReset; as pr) {
            <p class="note">
              Estado: <strong data-testid="password-reset-state">{{ pr.enabled ? 'Ativada' : 'Desativada' }}</strong>.
              O link vale 30 minutos e só pode ser usado uma vez; ao redefinir, as sessões abertas do usuário são encerradas.
            </p>
            @if (!pr.enabled && !pr.smtp_ready) {
              <p class="warn" data-testid="password-reset-hint">
                Para ativar: habilite o SMTP com STARTTLS ou SSL/TLS, salve e envie um e-mail de teste com sucesso.
                Qualquer alteração no SMTP desativa a recuperação e exige um novo teste. Apenas administradores podem ativar.
              </p>
            }
            <button mat-flat-button [color]="pr.enabled ? 'warn' : 'primary'" data-testid="password-reset-toggle"
                    [disabled]="savingPasswordReset || (!pr.enabled && !pr.smtp_ready)" (click)="togglePasswordReset()">
              <mat-icon>{{ pr.enabled ? 'lock' : 'lock_open' }}</mat-icon>
              {{ pr.enabled ? 'Desativar recuperação de senha' : 'Ativar recuperação de senha' }}
            </button>
          }
        </mat-card-content>
      </mat-card>
    </div>
  `,
  styles: [`
    .two-column-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 24px; }
    @media (max-width: 900px) { .two-column-grid { grid-template-columns: 1fr; } }
    .admin-card { border-radius: 12px; background: #fff; box-shadow: 0 1px 3px rgba(0,0,0,.06); border: 1px solid #e2e8f0; align-self: start; }
    .admin-card mat-card-header { margin-bottom: 16px; }
    .status-toggle-box { display: flex; justify-content: space-between; align-items: center; padding: 14px 18px; border-radius: 8px; background: #f1f5f9; margin-bottom: 20px; border: 1px solid #e2e8f0; }
    .status-toggle-box.active { background: #f0fdf4; border-color: #bbf7d0; }
    .status-toggle-box.active .toggle-info span { color: #16a34a; font-weight: 500; }
    .toggle-info { display: flex; flex-direction: column; gap: 2px; }
    .toggle-info strong { font-size: 14px; color: #1e293b; }
    .toggle-info span { font-size: 12px; color: #64748b; }
    .form-grid { display: flex; flex-direction: column; gap: 8px; }
    .pair { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
    .full-width { width: 100%; }
    .action-row { display: flex; gap: 12px; margin-top: 16px; }
    .note { font-size: 13px; color: #475569; }
    .warn { font-size: 13px; color: #92400e; }
    .feedback { margin-top: 16px; padding: 12px; border-radius: 6px; display: flex; align-items: center; gap: 8px; font-size: 13px; }
    .feedback.ok { background: #dcfce7; color: #166534; }
    .feedback.bad { background: #fee2e2; color: #991b1b; }
    .privacy { margin-top: 24px; padding: 12px; border-radius: 6px; background: #eff6ff; border: 1px solid #bfdbfe; display: flex; gap: 10px; }
    .privacy mat-icon { color: #2563eb; }
    .privacy div { font-size: 12px; color: #1e40af; }
    .privacy strong { display: block; margin-bottom: 2px; }
  `]
})
export class EmailConfigComponent implements OnInit {
  private adminService = inject(AdminService);
  private snackBar = inject(MatSnackBar);
  private cdr = inject(ChangeDetectorRef);

  smtpConfig: SmtpConfig = {
    is_enabled: false,
    host: 'smtp.gmail.com',
    port: 587,
    security: 'STARTTLS',
    username: '',
    from_email: 'suporte@empresa.com.br',
    from_name: 'Service Desk Central',
    app_base_url: 'http://localhost'
  };
  smtpPasswordInput = '';
  /** Falha ao ler a configuração salva: o formulário só tem os padrões do código e NÃO pode ser salvo por cima dela. */
  smtpLoadError: string | null = null;
  loadingSmtpConfig = false;
  savingSmtpConfig = false;
  testSmtpEmail = '';
  testingSmtp = false;
  smtpTestFeedback: { success: boolean; message: string } | null = null;

  passwordReset: PasswordResetConfig | null = null;
  passwordResetError: string | null = null;
  savingPasswordReset = false;

  ngOnInit(): void {
    this.loadSmtpConfig();
    this.loadPasswordReset();
  }

  loadSmtpConfig(): void {
    this.loadingSmtpConfig = true;
    this.smtpLoadError = null;
    this.adminService.getSmtpConfig().subscribe({
      next: (cfg) => {
        this.smtpConfig = cfg;
        this.smtpPasswordInput = cfg.password || '';
        this.loadingSmtpConfig = false;
        this.cdr.detectChanges();
      },
      error: (err) => {
        this.loadingSmtpConfig = false;
        this.smtpLoadError = apiErrorMessage(err, 'Não foi possível ler a configuração de e-mail salva.');
        this.cdr.detectChanges();
      }
    });
  }

  saveSmtpConfig(): void {
    // sem a configuração real carregada o formulário só tem os valores padrão do código: salvar apagaria a configuração de verdade
    if (this.smtpLoadError || this.loadingSmtpConfig) return;
    this.savingSmtpConfig = true;
    const payload: SmtpConfig = {
      ...this.smtpConfig,
      password: this.smtpPasswordInput ? this.smtpPasswordInput : undefined
    };
    this.adminService.updateSmtpConfig(payload).subscribe({
      next: (cfg) => {
        this.smtpConfig = cfg;
        this.smtpPasswordInput = cfg.password || '********';
        this.savingSmtpConfig = false;
        this.snackBar.open('Configurações de SMTP salvas com sucesso!', 'OK', { duration: 3000 });
        this.loadPasswordReset(); // alterar o SMTP desliga a recuperação de senha
      },
      error: (err) => {
        this.savingSmtpConfig = false;
        const msg = apiErrorMessage(err, 'Erro ao salvar configuração SMTP.');
        this.snackBar.open(msg, 'Fechar', { duration: 4000 });
      }
    });
  }

  loadPasswordReset(): void {
    this.passwordResetError = null;
    this.adminService.getPasswordResetConfig().subscribe({
      next: (cfg) => {
        this.passwordReset = cfg;
        this.cdr.detectChanges();
      },
      error: (err) => {
        this.passwordReset = null;
        this.passwordResetError = apiErrorMessage(err, 'Não foi possível ler o estado da recuperação de senha.');
        this.cdr.detectChanges();
      }
    });
  }

  togglePasswordReset(): void {
    if (!this.passwordReset || this.savingPasswordReset) return;
    const enable = !this.passwordReset.enabled;
    if (!enable) {
      this.applyPasswordReset(false);
      return;
    }
    // a confirmação mostra o que está SALVO no servidor (o formulário pode ter edições ainda não salvas):
    // o link de recuperação sai desse servidor e aponta para esse endereço
    this.savingPasswordReset = true;
    this.adminService.getSmtpConfig().subscribe({
      next: (saved) => {
        this.savingPasswordReset = false;
        const ok = confirm(
          'Ativar a recuperação de senha por e-mail?\n\n' +
          `Servidor: ${saved.host}:${saved.port}\n` +
          `Remetente: ${saved.from_email}\n` +
          `Endereço dos links: ${saved.app_base_url}\n\n` +
          'Qualquer pessoa poderá pedir um link por e-mail, sem estar logada. Confirme que esses dados estão corretos.'
        );
        if (ok) this.applyPasswordReset(true);
        else this.cdr.detectChanges();
      },
      error: (err) => {
        this.savingPasswordReset = false;
        this.snackBar.open(apiErrorMessage(err, 'Não foi possível ler a configuração de e-mail salva.'), 'Fechar', { duration: 6000 });
        this.cdr.detectChanges();
      }
    });
  }

  private applyPasswordReset(enable: boolean): void {
    this.savingPasswordReset = true;
    this.adminService.setPasswordReset(enable).subscribe({
      next: (cfg) => {
        this.passwordReset = cfg;
        this.savingPasswordReset = false;
        this.snackBar.open(enable ? 'Recuperação de senha ativada.' : 'Recuperação de senha desativada.', 'OK', { duration: 3000 });
        this.cdr.detectChanges();
      },
      error: (err) => {
        this.savingPasswordReset = false;
        this.snackBar.open(apiErrorMessage(err, 'Não foi possível alterar a recuperação de senha.'), 'Fechar', { duration: 6000 });
        this.cdr.detectChanges();
      }
    });
  }

  runSmtpTest(): void {
    if (!this.testSmtpEmail || !this.testSmtpEmail.includes('@')) {
      this.snackBar.open('Informe um e-mail de destino válido para o teste.', 'OK', { duration: 3000 });
      return;
    }
    this.testingSmtp = true;
    this.smtpTestFeedback = null;
    this.adminService.testSmtpConnection({
      target_email: this.testSmtpEmail,
      host: this.smtpConfig.host,
      port: this.smtpConfig.port,
      security: this.smtpConfig.security,
      username: this.smtpConfig.username,
      password: this.smtpPasswordInput && this.smtpPasswordInput !== '********' ? this.smtpPasswordInput : undefined,
      from_email: this.smtpConfig.from_email,
      from_name: this.smtpConfig.from_name
    }).subscribe({
      next: (res) => {
        this.testingSmtp = false;
        this.smtpTestFeedback = { success: true, message: `E-mail de teste enviado com sucesso para ${res.target_email}!` };
        this.loadPasswordReset(); // um teste ok homologa o SMTP salvo
      },
      error: (err) => {
        this.testingSmtp = false;
        this.smtpTestFeedback = { success: false, message: apiErrorMessage(err, 'Falha na conexão SMTP.') };
      }
    });
  }
}
