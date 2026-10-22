import { ChangeDetectorRef, Component, OnInit, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { AuthService } from '../../../core/auth/auth.service';
import { apiErrorMessage } from '../../../core/http/api-error';
import { Company, OrganizationService } from '../../../core/services/organization.service';
import { LoadStateComponent } from '../../../shared/components/load-state/load-state.component';

/** Limite do backend (`_LOGO_MAX_BYTES`): avisa antes de enviar um arquivo que seria recusado. */
const LOGO_MAX_BYTES = 2 * 1024 * 1024;
const LOGO_TYPES = ['image/png', 'image/jpeg', 'image/webp'];

@Component({
  selector: 'app-company',
  standalone: true,
  imports: [
    CommonModule,
    ReactiveFormsModule,
    MatButtonModule,
    MatFormFieldModule,
    MatIconModule,
    MatInputModule,
    MatSnackBarModule,
    LoadStateComponent
  ],
  template: `
    <div class="page-container">
      <div class="page-header">
        <div class="title-area">
          <h1>Empresa</h1>
          <p class="subtitle">Nome e logomarca exibidos no menu e na tela de login</p>
        </div>
      </div>

      <app-load-state [loading]="isLoading" [error]="loadError" loadingText="Carregando dados da empresa…" (retry)="load()"></app-load-state>

      <div class="company-card" *ngIf="company">
        <section class="logo-section">
          <div class="logo-preview">
            <img *ngIf="company.logo_url; else noLogo" [src]="company.logo_url" alt="Logomarca da empresa" data-testid="company-logo" />
            <ng-template #noLogo><mat-icon>domain</mat-icon></ng-template>
          </div>
          <div class="logo-actions" *ngIf="canEdit">
            <input #fileInput type="file" accept="image/png,image/jpeg,image/webp" hidden (change)="onLogoSelected($event)" />
            <button mat-stroked-button type="button" data-testid="logo-pick" [disabled]="uploadingLogo" (click)="fileInput.click()">
              <mat-icon>upload</mat-icon> {{ uploadingLogo ? 'Enviando…' : 'Trocar logomarca' }}
            </button>
            <small>PNG, JPEG ou WebP, até 2 MB.</small>
          </div>
        </section>

        <form [formGroup]="form" (ngSubmit)="save()" class="company-form">
          <mat-form-field appearance="outline">
            <mat-label>Nome da empresa</mat-label>
            <input matInput formControlName="name" maxlength="255" />
            <mat-error>O nome é obrigatório</mat-error>
          </mat-form-field>

          <mat-form-field appearance="outline">
            <mat-label>CNPJ</mat-label>
            <input matInput formControlName="cnpj" maxlength="20" />
          </mat-form-field>

          <div class="actions" *ngIf="canEdit">
            <button mat-flat-button color="primary" type="submit" data-testid="company-save" [disabled]="form.invalid || form.pristine || saving">
              {{ saving ? 'Salvando…' : 'Salvar' }}
            </button>
          </div>
        </form>
      </div>
    </div>
  `,
  styles: [
    `
      .company-card { display: flex; flex-direction: column; gap: 24px; max-width: 640px; background: #fff; border-radius: 12px; padding: 24px; box-shadow: 0 1px 3px rgba(0,0,0,.12); }
      .logo-section { display: flex; align-items: center; gap: 24px; flex-wrap: wrap; }
      .logo-preview { width: 96px; height: 96px; border-radius: 12px; border: 1px solid #e2e8f0; display: flex; align-items: center; justify-content: center; overflow: hidden; background: #f8fafc; }
      .logo-preview img { max-width: 100%; max-height: 100%; object-fit: contain; }
      .logo-preview mat-icon { font-size: 40px; width: 40px; height: 40px; opacity: .5; }
      .logo-actions { display: flex; flex-direction: column; gap: 6px; align-items: flex-start; }
      .logo-actions small { color: #64748b; }
      .company-form { display: flex; flex-direction: column; }
      .actions { display: flex; justify-content: flex-end; }
    `
  ]
})
export class CompanyComponent implements OnInit {
  private fb = inject(FormBuilder);
  private orgService = inject(OrganizationService);
  private auth = inject(AuthService);
  private snackBar = inject(MatSnackBar);
  private cdr = inject(ChangeDetectorRef);

  company: Company | null = null;
  isLoading = true;
  loadError: string | null = null;
  saving = false;
  uploadingLogo = false;

  readonly canEdit = this.auth.hasPermission('organization.company.update');

  form = this.fb.group({
    name: ['', [Validators.required, Validators.maxLength(255)]],
    cnpj: ['']
  });

  ngOnInit(): void {
    this.load();
  }

  load(): void {
    this.isLoading = true;
    this.loadError = null;
    this.orgService.getCompany().subscribe({
      next: (company) => {
        this.company = company;
        this.form.reset({ name: company.name, cnpj: company.cnpj ?? '' });
        if (!this.canEdit) this.form.disable();
        this.isLoading = false;
        this.cdr.markForCheck();
      },
      error: (err) => {
        this.company = null;
        this.isLoading = false;
        this.loadError = apiErrorMessage(err, 'Não foi possível carregar os dados da empresa.');
        this.cdr.markForCheck();
      }
    });
  }

  save(): void {
    if (this.form.invalid || this.saving || !this.canEdit) return;
    const { name, cnpj } = this.form.getRawValue();
    this.saving = true;
    this.orgService.updateCompany({ name: name!.trim(), cnpj: cnpj?.trim() || null }).subscribe({
      next: (company) => {
        this.company = company;
        this.form.reset({ name: company.name, cnpj: company.cnpj ?? '' });
        this.saving = false;
        this.orgService.branding$.next({ name: company.name, logo_url: company.logo_url });
        this.snackBar.open('Dados da empresa salvos.', 'Fechar', { duration: 3000 });
        this.cdr.markForCheck();
      },
      error: (err) => {
        this.saving = false;
        this.snackBar.open(apiErrorMessage(err, 'Não foi possível salvar os dados da empresa.'), 'Fechar', { duration: 5000 });
        this.cdr.markForCheck();
      }
    });
  }

  onLogoSelected(event: Event): void {
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0];
    input.value = ''; // permite escolher o mesmo arquivo de novo depois de uma falha
    if (!file || !this.canEdit) return;
    if (!LOGO_TYPES.includes(file.type)) {
      this.snackBar.open('Formato inválido. Use PNG, JPEG ou WebP.', 'Fechar', { duration: 5000 });
      return;
    }
    if (file.size > LOGO_MAX_BYTES) {
      this.snackBar.open('A logomarca deve ter no máximo 2 MB.', 'Fechar', { duration: 5000 });
      return;
    }
    this.uploadingLogo = true;
    this.orgService.uploadCompanyLogo(file).subscribe({
      next: (res) => {
        this.uploadingLogo = false;
        if (this.company) this.company = { ...this.company, logo_url: res.logo_url };
        this.orgService.branding$.next({ name: this.company?.name ?? '', logo_url: res.logo_url });
        this.snackBar.open('Logomarca atualizada.', 'Fechar', { duration: 3000 });
        this.cdr.markForCheck();
      },
      error: (err) => {
        this.uploadingLogo = false;
        this.snackBar.open(apiErrorMessage(err, 'Não foi possível enviar a logomarca.'), 'Fechar', { duration: 5000 });
        this.cdr.markForCheck();
      }
    });
  }
}
