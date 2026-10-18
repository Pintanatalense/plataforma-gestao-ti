import { Component, inject } from '@angular/core';
import { AbstractControl, FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { Router } from '@angular/router';

import { MatCardModule } from '@angular/material/card';
import { MatInputModule } from '@angular/material/input';
import { MatButtonModule } from '@angular/material/button';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatIconModule } from '@angular/material/icon';
import { MatRadioModule } from '@angular/material/radio';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';

import { AuthService } from '../../core/auth/auth.service';

@Component({
  selector: 'app-setup',
  standalone: true,
  imports: [
    ReactiveFormsModule,
    MatCardModule,
    MatInputModule,
    MatButtonModule,
    MatProgressSpinnerModule,
    MatIconModule,
    MatRadioModule,
    MatSnackBarModule,
  ],
  templateUrl: './setup.component.html',
  styleUrls: ['./setup.component.scss']
})
export class SetupComponent {
  private fb = inject(FormBuilder);
  private authService = inject(AuthService);
  private router = inject(Router);
  private snackBar = inject(MatSnackBar);

  setupForm = this.fb.group({
    email: ['', [Validators.required, Validators.email]],
    password: ['', [Validators.required, Validators.minLength(8)]],
    confirmPassword: ['', Validators.required],
    setup_mode: ['CLEAN', Validators.required],
    company_name: ['', Validators.required],
    company_cnpj: ['']
  }, { validators: SetupComponent.passwordMatch });

  isLoading = false;
  hidePassword = true;
  hideConfirm = true;
  error = '';

  constructor() {
    // O nome da empresa só é exigido na base limpa; no modelo de exemplo a empresa já vem pronta.
    this.setupForm.controls.setup_mode.valueChanges.subscribe((mode) => {
      const company = this.setupForm.controls.company_name;
      if (mode === 'CLEAN') company.addValidators(Validators.required);
      else company.clearValidators();
      company.updateValueAndValidity();
    });
  }

  get isClean(): boolean {
    return this.setupForm.controls.setup_mode.value === 'CLEAN';
  }

  static passwordMatch(group: AbstractControl) {
    return group.get('password')?.value === group.get('confirmPassword')?.value ? null : { mismatch: true };
  }

  onSubmit() {
    if (this.setupForm.invalid || this.isLoading) return;

    this.isLoading = true;
    this.error = '';
    const { email, password, setup_mode, company_name, company_cnpj } = this.setupForm.getRawValue();
    const payload = this.isClean
      ? { email, password, setup_mode, company_name: company_name?.trim(), company_cnpj: company_cnpj?.trim() || null }
      : { email, password, setup_mode };

    this.authService.setupFirstAdmin(payload).subscribe({
      next: () => {
        this.isLoading = false;
        this.snackBar.open('Instalação concluída! Bem-vindo.', 'Fechar', { duration: 3000 });
        this.router.navigate(['/']);
      },
      error: (err: any) => {
        this.isLoading = false;
        this.error = err?.error?.error?.message ?? 'Não foi possível concluir a instalação. Tente novamente.';
      }
    });
  }
}
