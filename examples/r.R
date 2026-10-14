# ---
# jupyter:
#   jupytext:
#     text_representation:
#       extension: .R
#       format_name: percent
#       format_version: '1.3'
#   kernelspec:
#     display_name: R
#     language: R
#     name: ir
# ---

# %% [markdown]
# # R notebook assistance example
#
# Change `value` from 1 to 2 through the notebook-refactor skill.
# The derived value and its display depend on the parameter; the final cell is independent.

# %%
value <- 1

# %%
value2 <- value * 10

# %%
print(value2)

# %%
print("Independent result")
