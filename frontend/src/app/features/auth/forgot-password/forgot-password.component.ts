import { ChangeDetectorRef, Component, OnInit, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { MatButtonModule } from '@angular/material/button';
import { MatCardModule } from '@angular/material/card';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { AuthService } from '../../../core/auth/auth.service';
import { apiErrorMessage } from '../../../core/http/api-error';

/** Pedido de link de recuperação. A resposta é sempre a mesma: a tela nunca revela se o e-mail está cadastrado. */
@Component({
  selector: 'app-forgot-password',
  standalone: true,
  imports: [
    CommonModule,
    ReactiveFormsModule,
    RouterLink,
    MatButtonModule,
    MatCardModule,
    MatIconModule,
    MatInputModule,
    MatProgressSpinnerModule
  ],
  template: `
    <div class="login-container">
      <mat-card class="login-card mat-elevation-z8">
        <mat-card-header>
          <div mat-card-avatar class="header-image"><mat-icon color="primary">lock_reset</mat-icon></div>
          <mat-card-title>Recuperar senha</mat-card-title>
          <mat-card-subtitle>Enviaremos um link para o seu e-mail</mat-card-subtitle>
        </mat-card-header>

        @if (checking) {
          <mat-card-content><div class="center"><mat-spinner diameter="28"></mat-spinner></div></mat-card-content>
        } @else if (!enabled) {
          <mat-card-content>
            <p data-testid="reset-unavailable">A recuperação de senha por e-mail não está disponível. Procure o suporte de TI.</p>
          </mat-card-content>
        } @else if (sent) {
          <mat-card-content>
            <p data-testid="reset-sent">{{ sentMessage }}</p>
            <p>O link vale por 30 minutos. Confira também a caixa de spam.</p>
          </mat-card-content>
        } @else {
          <form [formGroup]="form" (ngSubmit)="submit()">
            <mat-card-content>
              <mat-form-field appearance="outline" class="full-width">
                <mat-label>E-mail</mat-label>
                <input matInput type="email" formControlName="email" autocomplete="email" data-testid="reset-email" />
                <mat-icon matPrefix>email</mat-icon>
                <mat-error>Informe um e-mail válido</mat-error>
              </mat-form-field>
              @if (error) { <p class="form-error" role="alert" data-testid="reset-error">{{ error }}</p> }
            </mat-card-content>
            <mat-card-actions align="end">
              <button mat-raised-button color="primary" type="submit" data-testid="reset-submit" [disabled]="form.invalid || sending">
                {{ sending ? 'Enviando…' : 'Enviar link' }}
              </button>
            </mat-card-actions>
          </form>
        }
        <mat-card-actions align="start"><a mat-button routerLink="/login">Voltar ao login</a></mat-card-actions>
      </mat-card>
    </div>
  `,
  styleUrls: ['../login/login.component.scss'],
  styles: ['.center { display: flex; justify-content: center; padding: 16px; } .form-error { color: #b3261e; font-size: 13px; }']
})
export class ForgotPasswordComponent implements OnInit {
  private fb = inject(FormBuilder);
  private auth = inject(AuthService);
  private cdr = inject(ChangeDetectorRef);

  checking = true;
  enabled = false;
  sending = false;
  sent = false;
  sentMessage = '';
  error: string | null = null;

  form = this.fb.group({ email: ['', [Validators.required, Validators.email]] });

  ngOnInit(): void {
    this.auth.passwordResetStatus().subscribe({
      next: (res) => {
        this.enabled = !!res.enabled;
        this.checking = false;
        this.cdr.markForCheck();
      },
      error: () => {
        this.enabled = false;
        this.checking = false;
        this.cdr.markForCheck();
      }
    });
  }

  submit(): void {
    if (this.form.invalid || this.sending) return;
    this.sending = true;
    this.error = null;
    this.auth.requestPasswordReset(this.form.getRawValue().email!.trim()).subscribe({
      next: (res) => {
        this.sending = false;
        this.sent = true;
        this.sentMessage = res.message;
        this.cdr.markForCheck();
      },
      error: (err) => {
        this.sending = false;
        // 404 = a recuperação foi desativada nesse meio tempo; rede/5xx = tentar de novo
        this.error = apiErrorMessage(err, 'Não foi possível enviar o pedido. Tente novamente.');
        this.cdr.markForCheck();
      }
    });
  }
}
