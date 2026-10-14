import { Component, OnInit, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormBuilder, FormGroup, ReactiveFormsModule, Validators, FormControl } from '@angular/forms';
import { Router, RouterModule } from '@angular/router';
import { MatButtonModule } from '@angular/material/button';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';
import { MatIconModule } from '@angular/material/icon';
import { MatCheckboxModule } from '@angular/material/checkbox';
import { MatDividerModule } from '@angular/material/divider';
import { MatChipsModule } from '@angular/material/chips';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';

import { TicketService, TicketCategory, CategoryFormField } from '../ticket.service';
import { Asset, AssetService } from '../../../core/services/asset.service';
import { AuthService } from '../../../core/auth/auth.service';

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
    MatSnackBarModule
  ],
  templateUrl: './ticket-create.component.html',
  styleUrls: ['./ticket-create.component.scss']
})
export class TicketCreateComponent implements OnInit {
  private fb = inject(FormBuilder);
  private ticketService = inject(TicketService);
  private assetService = inject(AssetService);
  private router = inject(Router);
  private snackBar = inject(MatSnackBar);
  public authService = inject(AuthService);

  ticketForm: FormGroup;
  customFieldsForm: FormGroup;
  categories: TicketCategory[] = [];
  availableAssets: Asset[] = [];
  selectedCategory: TicketCategory | null = null;
  prerequisiteFields: CategoryFormField[] = [];

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
    this.ticketService.getCategories().subscribe({
      next: (data) => (this.categories = data),
      error: (err) => console.error(err)
    });

    if (this.authService.hasPermission('assets.read')) {
      this.assetService.getAssets().subscribe({
        next: (assets) => (this.availableAssets = assets),
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

    // Reconstrói dinamicamente os controles reativos para os pré-requisitos
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

      const initialValue = field.type === 'checkbox' ? false : '';
      group[field.id] = new FormControl(initialValue, validators);
    }

    this.customFieldsForm = new FormGroup(group);
  }

  onSubmit() {
    if (this.ticketForm.invalid) {
      this.ticketForm.markAllAsTouched();
      this.snackBar.open('Por favor, preencha os dados básicos do chamado.', 'Fechar', { duration: 3000 });
      return;
    }

    // Se a categoria tem pré-requisitos, validação estrita antes do envio
    if (this.prerequisiteFields.length > 0 && this.customFieldsForm.invalid) {
      this.customFieldsForm.markAllAsTouched();
      this.snackBar.open(
        'Atenção: Todos os pré-requisitos obrigatórios desta categoria devem ser preenchidos.',
        'Fechar',
        { duration: 5000 }
      );
      return;
    }

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
      next: (ticket) => {
        this.snackBar.open('Chamado aberto com sucesso!', 'Fechar', { duration: 3000 });
        this.router.navigate(['/service-desk', ticket.id]);
      },
      error: (err) => {
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
