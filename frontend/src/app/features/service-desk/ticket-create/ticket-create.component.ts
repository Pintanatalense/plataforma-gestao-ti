import { Component, OnInit, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormBuilder, FormGroup, ReactiveFormsModule, Validators, FormControl } from '@angular/forms';
import { ActivatedRoute, Router, RouterModule } from '@angular/router';
import { MatButtonModule } from '@angular/material/button';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';
import { MatIconModule } from '@angular/material/icon';
import { MatCheckboxModule } from '@angular/material/checkbox';
import { MatDividerModule } from '@angular/material/divider';
import { MatChipsModule } from '@angular/material/chips';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatTooltipModule } from '@angular/material/tooltip';
import { firstValueFrom } from 'rxjs';

import { TicketService, TicketCategory, CategoryFormField } from '../ticket.service';
import { Asset, AssetService } from '../../../core/services/asset.service';
import { AuthService } from '../../../core/auth/auth.service';
import { AttachmentsService } from '../../../core/services/attachments.service';

@Component({
  selector: 'app-ticket-create',
  standalone: true,
  imports: [
    CommonModule,
    ReactiveFormsModule,
    RouterModule,
    MatButtonModule,
    MatInputModule,
    MatSelectModule,
    MatIconModule,
    MatCheckboxModule,
    MatDividerModule,
    MatChipsModule,
    MatSnackBarModule,
    MatProgressBarModule,
    MatTooltipModule
  ],
  templateUrl: './ticket-create.component.html',
  styleUrls: ['./ticket-create.component.scss']
})
export class TicketCreateComponent implements OnInit {
  private fb = inject(FormBuilder);
  private ticketService = inject(TicketService);
  private assetService = inject(AssetService);
  private attachmentsService = inject(AttachmentsService);
  private router = inject(Router);
  private route = inject(ActivatedRoute);
  private snackBar = inject(MatSnackBar);
  public authService = inject(AuthService);

  ticketForm: FormGroup;
  customFieldsForm: FormGroup;
  categories: TicketCategory[] = [];
  availableAssets: Asset[] = [];
  selectedCategory: TicketCategory | null = null;
  prerequisiteFields: CategoryFormField[] = [];

  selectedFiles: File[] = [];
  isSubmitting = false;
  uploadProgressText = '';

  constructor() {
    this.ticketForm = this.fb.group({
      title: ['', Validators.required],
      description: ['', Validators.required],
      priority: ['LOW', Validators.required],
      category_id: [null],
      asset_id: [null]
    });

    this.customFieldsForm = this.fb.group({});
  }

  ngOnInit() {
    const preselectedAssetId = this.route.snapshot.queryParamMap.get('asset_id');

    this.ticketService.getCategories().subscribe({
      next: (data) => (this.categories = data),
      error: (err) => console.error(err)
    });

    if (this.authService.hasPermission('assets.read')) {
      this.assetService.getAssets().subscribe({
        next: (assets) => {
          this.availableAssets = assets;
          if (preselectedAssetId && this.availableAssets.some((a) => a.id === preselectedAssetId)) {
            this.ticketForm.patchValue({ asset_id: preselectedAssetId });
          }
        },
        error: () => {}
      });
    } else {
      this.assetService.getMyAssets().subscribe({
        next: (assets) => {
          this.availableAssets = assets;
          if (preselectedAssetId && this.availableAssets.some((a) => a.id === preselectedAssetId)) {
            this.ticketForm.patchValue({ asset_id: preselectedAssetId });
          }
        },
        error: () => {}
      });
    }

    this.ticketForm.get('category_id')?.valueChanges.subscribe((catId) => {
      this.onCategorySelected(catId);
    });
  }

  onCategorySelected(catId: string | null) {
    if (!catId) {
      this.selectedCategory = null;
      this.prerequisiteFields = [];
      this.customFieldsForm = this.fb.group({});
      return;
    }

    const cat = this.categories.find(c => c.id === catId);
    this.selectedCategory = cat || null;
    this.prerequisiteFields = cat?.form_schema || [];

    const group: Record<string, FormControl> = {};
    for (const field of this.prerequisiteFields) {
      const validators = [];
      if (field.required) {
        if (field.type === 'checkbox') {
          validators.push(Validators.requiredTrue);
        } else {
          validators.push(Validators.required);
        }
      }
      group[field.id] = new FormControl(
        field.type === 'checkbox' ? false : '',
        validators
      );
    }
    this.customFieldsForm = this.fb.group(group);
  }

  onFilesSelected(event: any): void {
    const files: FileList = event.target.files;
    if (files) {
      for (let i = 0; i < files.length; i++) {
        this.selectedFiles.push(files[i]);
      }
    }
    event.target.value = null;
  }

  removeSelectedFile(index: number): void {
    this.selectedFiles.splice(index, 1);
  }

  formatFileSize(bytes: number): string {
    return this.attachmentsService.formatBytes(bytes);
  }

  onSubmit() {
    if (this.ticketForm.invalid) {
      this.ticketForm.markAllAsTouched();
      return;
    }

    if (this.prerequisiteFields.length > 0 && this.customFieldsForm.invalid) {
      this.customFieldsForm.markAllAsTouched();
      this.snackBar.open(
        'Atenção: Todos os pré-requisitos obrigatórios desta categoria devem ser preenchidos.',
        'Fechar',
        { duration: 5000 }
      );
      return;
    }

    this.isSubmitting = true;
    this.uploadProgressText = '';

    const val = this.ticketForm.value;
    const customFieldsVal = this.customFieldsForm.value;

    const payload: any = {
      title: val.title,
      description: val.description,
      priority: val.priority,
      category_id: val.category_id || undefined,
      asset_ids: val.asset_id ? [val.asset_id] : [],
      custom_fields: customFieldsVal
    };

    this.ticketService.createTicket(payload).subscribe({
      next: async (ticket) => {
        if (this.selectedFiles.length > 0) {
          this.uploadProgressText = `Enviando ${this.selectedFiles.length} anexo(s)...`;
          for (let i = 0; i < this.selectedFiles.length; i++) {
            const f = this.selectedFiles[i];
            try {
              await firstValueFrom(this.attachmentsService.uploadFile(f, 'TICKET', ticket.id));
            } catch (err) {
              console.error('Erro ao enviar anexo:', f.name, err);
            }
          }
        }

        this.isSubmitting = false;
        const msg = this.selectedFiles.length > 0
          ? `Chamado aberto com sucesso com ${this.selectedFiles.length} anexo(s) vinculado(s)!`
          : 'Chamado aberto com sucesso!';
        this.snackBar.open(msg, 'Fechar', { duration: 4000 });
        this.router.navigate(['/service-desk', ticket.id]);
      },
      error: (err) => {
        this.isSubmitting = false;
        console.error(err);
        const msg =
          err?.error?.error?.message ||
          err?.error?.detail ||
          'Erro ao abrir chamado. Verifique os pré-requisitos.';
        this.snackBar.open(msg, 'Fechar', { duration: 6000 });
      }
    });
  }
}
