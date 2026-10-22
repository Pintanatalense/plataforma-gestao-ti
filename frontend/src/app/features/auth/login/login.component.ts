import { ChangeDetectorRef, Component, inject, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { Router } from '@angular/router';

import { MatCardModule } from '@angular/material/card';
import { MatInputModule } from '@angular/material/input';
import { MatButtonModule } from '@angular/material/button';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatIconModule } from '@angular/material/icon';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';

import { AuthService } from '../../../core/auth/auth.service';
import { apiErrorMessage } from '../../../core/http/api-error';
import { OrganizationService } from '../../../core/services/organization.service';

@Component({
  selector: 'app-login',
  standalone: true,
  imports: [
    CommonModule,
    ReactiveFormsModule,
    MatCardModule,
    MatInputModule,
    MatButtonModule,
    MatProgressSpinnerModule,
    MatIconModule,
    MatSnackBarModule,
  ],
  templateUrl: './login.component.html',
  styleUrls: ['./login.component.scss']
})
export class LoginComponent implements OnInit {
  private fb = inject(FormBuilder);
  private authService = inject(AuthService);
  private router = inject(Router);
  private snackBar = inject(MatSnackBar);
  private orgService = inject(OrganizationService);
  private cdr = inject(ChangeDetectorRef);

  companyName = 'Gestão de TI';
  companyLogoUrl: string | null = null;

  loginForm = this.fb.group({
    email: ['', [Validators.required, Validators.email]],
    password: ['', Validators.required]
  });

  isLoading = false;
  hidePassword = true;

  ngOnInit() {
    this.orgService.branding$.subscribe((branding) => {
      if (!branding) return;
      this.companyName = branding.name || 'Gestão de TI';
      this.companyLogoUrl = branding.logo_url;
      this.cdr.markForCheck();
    });
    this.orgService.loadBranding();
    this.authService.getSetupStatus().subscribe(res => {
      if (res.setup_required) {
        this.router.navigate(['/setup']);
      }
    });
  }

  onLogoError(): void {
    this.companyLogoUrl = null;
  }

  onSubmit() {
    if (this.loginForm.invalid) return;

    this.isLoading = true;
    const { email, password } = this.loginForm.value;

    this.authService.login(email!, password!).subscribe({
      next: () => {
        this.isLoading = false;
        // volta à página em que a sessão caiu (se houver); senão, ao painel
        this.router.navigateByUrl(this.authService.takeReturnUrl() ?? '/');
      },
      error: (err: any) => {
        this.isLoading = false;
        // sem conexão / erro do servidor: o interceptor já avisou (evita dois avisos iguais empilhados)
        if (err?.status === 0 || err?.status >= 500) return;
        this.snackBar.open(apiErrorMessage(err, 'Não foi possível entrar. Tente novamente.'), 'Fechar', {
          duration: 5000,
          panelClass: ['error-snackbar']
        });
      }
    });
  }
}
