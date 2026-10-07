import { Component, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { MatCardModule } from '@angular/material/card';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { Router } from '@angular/router';
import { AuthService } from '../../../core/auth/auth.service';

@Component({
  selector: 'app-change-password',
  standalone: true,
  imports: [
    CommonModule,
    ReactiveFormsModule,
    MatCardModule,
    MatFormFieldModule,
    MatInputModule,
    MatButtonModule,
    MatIconModule,
    MatProgressSpinnerModule,
    MatSnackBarModule
  ],
  templateUrl: './change-password.component.html',
  styleUrls: ['./change-password.component.scss']
})
export class ChangePasswordComponent {
  private fb = inject(FormBuilder);
  private authService = inject(AuthService);
  private router = inject(Router);
  private snackBar = inject(MatSnackBar);

  isLoading = false;
  hideCurrent = true;
  hideNew = true;

  form = this.fb.group({
    currentPassword: ['', Validators.required],
    newPassword: ['', [Validators.required, Validators.minLength(8)]]
  });

  onSubmit() {
    if (this.form.invalid) return;

    this.isLoading = true;
    const { currentPassword, newPassword } = this.form.value;

    this.authService.changeOwnPassword(currentPassword!, newPassword!).subscribe({
      next: () => {
        this.snackBar.open('Senha alterada com sucesso!', 'Fechar', { duration: 3000 });
        this.router.navigate(['/dashboard']);
      },
      error: (err) => {
        this.isLoading = false;
        const msg = err.error?.detail || 'Erro ao alterar senha.';
        this.snackBar.open(msg, 'Fechar', { duration: 5000, panelClass: 'error-snackbar' });
      }
    });
  }
}
