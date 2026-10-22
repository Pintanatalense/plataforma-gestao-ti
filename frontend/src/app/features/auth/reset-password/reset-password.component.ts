import { ChangeDetectorRef, Component, OnInit, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { AbstractControl, FormBuilder, ReactiveFormsModule, ValidationErrors, Validators } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { MatButtonModule } from '@angular/material/button';
import { MatCardModule } from '@angular/material/card';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { AuthService } from '../../../core/auth/auth.service';
import { apiErrorMessage } from '../../../core/http/api-error';

const matchPasswords = (group: AbstractControl): ValidationErrors | null =>
  group.get('password')?.value === group.get('confirm')?.value ? null : { mismatch: true };

/** Destino do link do e-mail (`/reset-password?token=...`). O token sai da barra de endereço assim que a tela abre. */
@Component({
  selector: 'app-reset-password',
  standalone: true,
  imports: [CommonModule, ReactiveFormsModule, RouterLink, MatButtonModule, MatCardModule, MatIconModule, MatInputModule],
  template: `
    <div class="login-container">
      <mat-card class="login-card mat-elevation-z8">
        <mat-card-header>
          <div mat-card-avatar class="header-image"><mat-icon color="primary">lock_reset</mat-icon></div>
          <mat-card-title>Definir nova senha</mat-card-title>
        </mat-card-header>

        @if (done) {
          <mat-card-content>
            <p data-testid="reset-done">Senha redefinida. Entre com a nova senha.</p>
          </mat-card-content>
          <mat-card-actions align="end"><a mat-raised-button color="primary" routerLink="/login">Ir para o login</a></mat-card-actions>
        } @else if (!token) {
          <mat-card-content>
            <p data-testid="reset-no-token">Link inválido ou expirado. Peça um novo link de recuperação.</p>
          </mat-card-content>
          <mat-card-actions align="end"><a mat-raised-button color="primary" routerLink="/forgot-password">Pedir novo link</a></mat-card-actions>
        } @else {
          <form [formGroup]="form" (ngSubmit)="submit()">
            <mat-card-content>
              <mat-form-field appearance="outline" class="full-width">
                <mat-label>Nova senha</mat-label>
                <input matInput type="password" formControlName="password" autocomplete="new-password" data-testid="reset-password" />
                <mat-error>Mínimo de 8 caracteres</mat-error>
              </mat-form-field>
              <mat-form-field appearance="outline" class="full-width">
                <mat-label>Confirmar nova senha</mat-label>
                <input matInput type="password" formControlName="confirm" autocomplete="new-password" data-testid="reset-confirm" />
              </mat-form-field>
              @if (form.hasError('mismatch') && form.controls.confirm.dirty) {
                <p class="form-error" data-testid="reset-mismatch">As senhas não conferem.</p>
              }
              @if (error) { <p class="form-error" role="alert" data-testid="reset-error">{{ error }}</p> }
            </mat-card-content>
            <mat-card-actions align="end">
              <button mat-raised-button color="primary" type="submit" data-testid="reset-submit" [disabled]="form.invalid || sending">
                {{ sending ? 'Salvando…' : 'Redefinir senha' }}
              </button>
            </mat-card-actions>
          </form>
        }
      </mat-card>
    </div>
  `,
  styleUrls: ['../login/login.component.scss'],
  styles: ['.form-error { color: #b3261e; font-size: 13px; }']
})
export class ResetPasswordComponent implements OnInit {
  private fb = inject(FormBuilder);
  private auth = inject(AuthService);
  private route = inject(ActivatedRoute);
  private router = inject(Router);
  private cdr = inject(ChangeDetectorRef);

  token: string | null = null;
  sending = false;
  done = false;
  error: string | null = null;

  form = this.fb.group(
    {
      password: ['', [Validators.required, Validators.minLength(8), Validators.maxLength(128)]],
      confirm: ['', Validators.required]
    },
    { validators: matchPasswords }
  );

  ngOnInit(): void {
    this.token = this.route.snapshot.queryParamMap.get('token');
    if (this.token) {
      // tira o token da URL (histórico, favoritos, capturas de tela); ele fica só em memória nesta tela
      void this.router.navigate([], { queryParams: { token: null }, queryParamsHandling: 'merge', replaceUrl: true });
    }
  }

  submit(): void {
    if (this.form.invalid || this.sending || !this.token) return;
    this.sending = true;
    this.error = null;
    this.auth.confirmPasswordReset(this.token, this.form.getRawValue().password!).subscribe({
      next: () => {
        this.sending = false;
        this.done = true;
        this.token = null;
        this.cdr.markForCheck();
      },
      error: (err) => {
        this.sending = false;
        this.error = apiErrorMessage(err, 'Não foi possível redefinir a senha. Tente novamente.');
        this.cdr.markForCheck();
      }
    });
  }
}
