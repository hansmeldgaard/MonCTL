import { useState, useCallback } from "react";
import type { ValidationResult } from "@/lib/validation";

type ValidatorFn = (value: string) => ValidationResult;

interface FieldState {
  value: string;
  error: string | null;
  touched: boolean;
}

/**
 * Hook for inline field-level validation.
 *
 * Usage:
 *   const name = useField("", validateName);
 *   <Input {...name.inputProps} />
 *   // On submit: if (name.validate()) { ... proceed ... }
 */
export function useField(initialValue: string, validator?: ValidatorFn) {
  const [state, setState] = useState<FieldState>({
    value: initialValue,
    error: null,
    touched: false,
  });

  const onChange = useCallback(
    (
      e: React.ChangeEvent<
        HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement
      >,
    ) => {
      const newValue = e.target.value;
      setState((prev) => {
        const error = prev.touched && validator ? validator(newValue) : null;
        return { value: newValue, error, touched: prev.touched };
      });
    },
    [validator],
  );

  const setValue = useCallback(
    (newValue: string) => {
      setState((prev) => {
        const error = prev.touched && validator ? validator(newValue) : null;
        return { value: newValue, error, touched: prev.touched };
      });
    },
    [validator],
  );

  const onBlur = useCallback(() => {
    setState((prev) => ({
      ...prev,
      touched: true,
      error: validator ? validator(prev.value) : null,
    }));
  }, [validator]);

  /** Force-validate and return true if valid. */
  const validate = useCallback((): boolean => {
    const error = validator ? validator(state.value) : null;
    setState((prev) => ({ ...prev, touched: true, error }));
    return error === null;
  }, [validator, state.value]);

  const reset = useCallback(
    (newValue = initialValue) => {
      setState({ value: newValue, error: null, touched: false });
    },
    [initialValue],
  );

  return {
    value: state.value,
    error: state.touched ? state.error : null,
    touched: state.touched,
    onChange,
    onBlur,
    setValue,
    validate,
    reset,
    inputProps: {
      value: state.value,
      onChange,
      onBlur,
    },
  };
}

/**
 * Validate all fields and return true if all valid.
 * Usage: if (validateAll(nameField, addressField)) { submit(); }
 */
export function validateAll(...fields: { validate: () => boolean }[]): boolean {
  return fields.map((f) => f.validate()).every(Boolean);
}
